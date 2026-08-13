"""Optional: generates the openWakeWord training config for a custom model.

You do not need this. The default `whisper` wake-word backend answers to any phrase with
nothing trained. Train an openWakeWord model only if you want that backend's lower CPU cost
in a room where the microphone is rarely quiet.

Training itself needs a GPU box with several GB of negative-audio datasets, so the practical
path is the official Colab notebook. This script writes the config that notebook consumes and
tells you exactly what to do with it. Run it, then follow the printed steps.

    python scripts/train_wakeword.py
    python scripts/train_wakeword.py --phrase "hey computer" --output models/hey_computer.onnx
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

NOTEBOOK_URL = (
    "https://colab.research.google.com/github/dscripka/openWakeWord/blob/main/notebooks/"
    "automatic_model_training.ipynb"
)

CONFIG_TEMPLATE = """\
# openWakeWord training config for Ghostwriter.
# Feed this to the automatic_model_training.ipynb Colab notebook.
target_phrase:
{phrases}
model_name: {model_name}

# Synthetic clips generated per phrase. More is better; these defaults train in about an hour.
n_samples: 5000
n_samples_val: 1000

# Augmentation. Room impulse responses and background noise are what make the model robust
# to your actual room rather than to clean TTS audio.
augmentation_rounds: 1
augmentation_batch_size: 16
tts_batch_size: 50

steps: 50000
max_negative_weight: 1500
target_accuracy: 0.7
target_recall: 0.25

output_dir: ./my_custom_model
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phrase", default="hey ghost", help="wake phrase to train")
    parser.add_argument(
        "--output",
        default="models/hey_ghost.onnx",
        help="where the trained .onnx will live, relative to the project root",
    )
    args = parser.parse_args()

    model_name = Path(args.output).stem
    # Spelling variants materially improve recall: the TTS voices stress "ghostwriter"
    # inconsistently, and training on one pronunciation makes the model brittle to the others.
    variants = [args.phrase]
    if args.phrase == "hey ghost":
        variants += ["hey, ghost", "hey goast", "hey gost", "hey ghosts"]

    config = CONFIG_TEMPLATE.format(
        phrases="\n".join(f"  - {phrase}" for phrase in dict.fromkeys(variants)),
        model_name=model_name,
    )

    config_path = ROOT / "models" / f"{model_name}_training.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config, encoding="utf-8")

    print(f"Wrote {config_path}\n")
    print("Next steps:")
    print(f"  1. Open the training notebook: {NOTEBOOK_URL}")
    print("  2. Runtime > Change runtime type > T4 GPU (free tier is enough).")
    print(f"  3. Upload {config_path.name} and point the notebook's config path at it.")
    print("  4. Run all cells. Expect roughly 1 hour, mostly dataset downloads.")
    print(f"  5. Download the resulting {model_name}.onnx into {ROOT / args.output}")
    print(f"  6. In config.toml set backend = \"openwakeword\" and model_path = {args.output!r}.")
    print("  7. Restart Ghostwriter.")
    print("\nUntil then the whisper backend answers to the phrase with nothing trained.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
