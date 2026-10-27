from pathlib import Path
import copy
import json
import time

import joblib
import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data/synthea_prepared_v1"
OUT = ROOT / "artifacts/synthea_autoencoder_v1"
OUT.mkdir(parents=True, exist_ok=True)

torch.manual_seed(42)
np.random.seed(42)

device = torch.device(
    "mps" if torch.backends.mps.is_available() else "cpu"
)
print("Training device:", device, flush=True)

metadata = json.loads((DATA / "metadata.json").read_text())
features = metadata["features"]

frames = {
    name: pd.read_csv(DATA / f"{name}.csv")
    for name in ["train", "validation", "test"]
}

# Verify patient separation before training.
patient_sets = {
    name: set(frame["PATIENT"])
    for name, frame in frames.items()
}
assert patient_sets["train"].isdisjoint(patient_sets["validation"])
assert patient_sets["train"].isdisjoint(patient_sets["test"])
assert patient_sets["validation"].isdisjoint(patient_sets["test"])

for name, frame in frames.items():
    values = frame[features].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError(f"{name} contains missing or infinite values")

# Learn preprocessing from TRAINING DATA ONLY.
scaler = StandardScaler()
scaler.fit(frames["train"][features])

arrays = {
    name: scaler.transform(frame[features]).astype("float32")
    for name, frame in frames.items()
}

loader = DataLoader(
    TensorDataset(torch.from_numpy(arrays["train"])),
    batch_size=256,
    shuffle=True,
    num_workers=0,
)

widths = [len(features), 64, 32, 4, 32, 64, len(features)]
layers = []

for i in range(len(widths) - 1):
    layers.append(nn.Linear(widths[i], widths[i + 1]))
    if i < len(widths) - 2:
        layers.append(nn.ReLU())

model = nn.Sequential(*layers).to(device)
optimizer = torch.optim.Adam(
    model.parameters(), lr=0.001, weight_decay=0.00001
)
loss_function = nn.MSELoss()

print("Architecture:", widths)
print("Trainable parameters:",
      sum(p.numel() for p in model.parameters()))
print("Training rows:", len(arrays["train"]), flush=True)


def reconstruction_scores(array):
    model.eval()
    scores = []

    with torch.no_grad():
        for start in range(0, len(array), 1024):
            batch = torch.from_numpy(
                array[start:start + 1024]
            ).to(device)
            reconstructed = model(batch)
            error = ((reconstructed - batch) ** 2).mean(dim=1)
            scores.append(error.cpu().numpy())

    return np.concatenate(scores)


best_loss = float("inf")
best_weights = None
best_epoch = None
patience = 15
stale_epochs = 0
history = []
started = time.perf_counter()

for epoch in range(1, 151):
    model.train()
    total_loss = 0.0

    for (batch,) in loader:
        batch = batch.to(device)
        optimizer.zero_grad()

        reconstructed = model(batch)
        loss = loss_function(reconstructed, batch)

        if not torch.isfinite(loss):
            raise RuntimeError("Non-finite training loss")

        loss.backward()
        optimizer.step()

        total_loss += loss.item() * len(batch)

    train_loss = total_loss / len(arrays["train"])
    validation_loss = float(
        reconstruction_scores(arrays["validation"]).mean()
    )

    history.append({
        "epoch": epoch,
        "train_mse": train_loss,
        "validation_mse": validation_loss,
    })

    print(
        f"Epoch {epoch:03d}/150 | "
        f"train MSE={train_loss:.6f} | "
        f"validation MSE={validation_loss:.6f}",
        flush=True,
    )

    if validation_loss < best_loss - 1e-6:
        best_loss = validation_loss
        best_epoch = epoch
        best_weights = copy.deepcopy(model.state_dict())
        stale_epochs = 0
    else:
        stale_epochs += 1

    if stale_epochs >= patience:
        print("Early stopping: validation loss stopped improving.")
        break

training_seconds = time.perf_counter() - started
model.load_state_dict(best_weights)
model.eval()

validation_scores = reconstruction_scores(arrays["validation"])
test_scores = reconstruction_scores(arrays["test"])

# Provisional review threshold, not a clinically validated cutoff.
# It selects roughly the highest-scoring 5% of validation panels.
ae_threshold = float(np.quantile(validation_scores, 0.95))

print("\nTraining Isolation Forest baseline...", flush=True)
baseline = IsolationForest(
    n_estimators=300,
    max_samples=256,
    random_state=42,
    n_jobs=-1,
)
baseline.fit(arrays["train"])

if_validation = -baseline.score_samples(arrays["validation"])
if_test = -baseline.score_samples(arrays["test"])
if_threshold = float(np.quantile(if_validation, 0.95))

# Save weights on CPU so they can be loaded on CPU or GPU later.
cpu_weights = {
    key: value.detach().cpu()
    for key, value in model.state_dict().items()
}
torch.save(cpu_weights, OUT / "autoencoder_weights.pt")
joblib.dump(scaler, OUT / "scaler.joblib")
joblib.dump(baseline, OUT / "isolation_forest.joblib")

config = {
    **metadata,
    "architecture": widths,
    "hidden_activation": "ReLU",
    "output_activation": "linear",
    "autoencoder_score": "mean_squared_error_in_standardized_space",
    "autoencoder_threshold": ae_threshold,
    "isolation_forest_score": "negative_score_samples",
    "isolation_forest_threshold": if_threshold,
    "threshold_method": "95th percentile of validation scores",
    "scope": "Synthetic experiment; thresholds are not clinical cutoffs",
}
(OUT / "config.json").write_text(json.dumps(config, indent=2))

results = frames["test"][["PATIENT", "ENCOUNTER", "DATE"]].copy()
results["autoencoder_score"] = test_scores
results["autoencoder_flag"] = test_scores >= ae_threshold
results["isolation_forest_score"] = if_test
results["isolation_forest_flag"] = if_test >= if_threshold
results.to_csv(OUT / "test_scores.csv", index=False)

report = {
    "device": str(device),
    "trainable_parameters": sum(p.numel() for p in model.parameters()),
    "epochs_run": len(history),
    "best_epoch": best_epoch,
    "training_seconds": round(training_seconds, 2),
    "best_validation_mse": best_loss,
    "test_mse": float(test_scores.mean()),
    "autoencoder_test_flag_rate": float(
        (test_scores >= ae_threshold).mean()
    ),
    "isolation_forest_test_flag_rate": float(
        (if_test >= if_threshold).mean()
    ),
    "note": (
        "No anomaly labels are available. Flag rates are not "
        "accuracy, precision, recall, or false-positive rates."
    ),
}

pd.DataFrame(history).to_csv(OUT / "training_history.csv", index=False)
(OUT / "training_report.json").write_text(json.dumps(report, indent=2))
(OUT / "versions.json").write_text(json.dumps({
    "torch": str(torch.__version__),
    "numpy": np.__version__,
    "pandas": pd.__version__,
    "sklearn": __import__("sklearn").__version__,
}, indent=2))

print("\nTraining finished:")
print(json.dumps(report, indent=2))
print("\nArtifacts saved to:", OUT)
