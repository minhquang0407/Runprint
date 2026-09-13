"""
Example PyTorch/ML Training Script with Tiny QR SDK
===================================================
Run with:
  qr run -- python examples/pytorch/dummy_train.py --epochs 3
"""

import argparse
import time
from pathlib import Path

# QR SDK can be imported and will safely no-op if run outside QR wrapper
import qr


def main():
    parser = argparse.ArgumentParser(description="Dummy training script")
    parser.add_argument("--config", type=str, default=None, help="Path to YAML/JSON config file")
    parser.add_argument("--epochs", type=int, default=3, help="Number of training epochs")
    parser.add_argument("--lr", type=float, default=0.001, help="Learning rate")
    args = parser.parse_args()

    cfg_str = f" [config: {args.config}]" if args.config else ""
    print(f"Starting training with epochs={args.epochs}, lr={args.lr}{cfg_str}")

    # Declare dataset input provenance
    qr.input_dataset(
        name="synthetic_vision_dataset",
        uri="/data/synthetic_v1",
        version="v1.0",
        fingerprint="sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )

    loss = 1.0
    accuracy = 0.50

    for epoch in range(1, args.epochs + 1):
        time.sleep(0.5)
        loss *= 0.7
        accuracy += (1.0 - accuracy) * 0.3

        print(f"Epoch {epoch}/{args.epochs} - loss: {loss:.4f} - accuracy: {accuracy:.4f}")

        # Structured metric logging
        qr.log({
            "epoch": epoch,
            "loss": round(loss, 4),
            "accuracy": round(accuracy, 4),
        })

    # Save a dummy model checkpoint artifact
    checkpoint_dir = Path("checkpoints")
    checkpoint_dir.mkdir(exist_ok=True)
    checkpoint_file = checkpoint_dir / "best_model.pt"
    checkpoint_file.write_text(f"dummy model weights (accuracy={accuracy:.4f})\n", encoding="utf-8")

    # Register artifact reference
    qr.artifact(str(checkpoint_file), kind="model", metadata={"accuracy": accuracy})

    print("Training finished! Checkpoint saved.")


if __name__ == "__main__":
    main()
