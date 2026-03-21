# How to Train Your "Hey AVA" Custom Wake Word

OpenWakeWord takes a revolutionary approach to wake word training. Instead of making you record your voice saying "Hey AVA" a thousand times, it uses **Text-To-Speech (TTS) models** to generate thousands of synthetic voices saying "Hey AVA". It then trains a lightweight neural network (saved as a `.onnx` file) on those synthetic voices mixed with background noise.

Because generating thousands of synthetic TTS voices requires significant CPU/GPU power and gigabytes of background noise data, **the recommended way to train is using the official Google Colab notebook.**

## Step 1: Open the Colab Notebook

Go to the official OpenWakeWord zero-shot training notebook:  
👉 [openWakeWord Training Colab](https://colab.research.google.com/github/dscripka/openWakeWord/blob/main/notebooks/openwakeword_model_training.ipynb)

> _Note: You will need a standard Google Account to run Colab (free tier is usually fine)._

## Step 2: Configure the Training

1. In the notebook, scroll to the **Target Word/Phrase Setup** section.
2. Ensure you change the target parameter to `"hey ava"`.
3. Read the documentation in the cell regarding phonetic spelling (e.g. you might need to try `"hey ay vuh"` depending on how the TTS pronounces "AVA", but `"hey ava"` usually works fine).
4. Run all the cells sequentially (Runtime -> Run all).

## Step 3: Download your Model

The script will automatically:

1. Generate synthetic voices speaking your phrase using Piper TTS.
2. Mix the speech with background noise (music, talking, traffic).
3. Train the model for several epochs (usually takes ~45 minutes to 1 hour).
4. Export the final model file.

Once complete, the notebook will generate a `.onnx` file (likely named `hey_ava.onnx`). **Download this file.**

## Step 4: Add to your Project

1. Move the downloaded `hey_ava.onnx` file into your `ava/` directory:  
   `project-AVA-code-optimizations/ava/hey_ava.onnx`
2. Run your project! `voice_processor.py` is already configured to read `hey_ava.onnx`.

> **Troubleshooting Thresholds**  
> If AVA is waking up when you didn't call her, open the `.env` file and increase `WAKE_WORD_THRESHOLD` from `0.5` to `0.6` or `0.7`.  
> If AVA is ignoring you, lower the threshold to `0.3` or `0.4`.
