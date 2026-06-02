"""
Local Intent Classifier for AVA.
Uses TF-IDF + SGDClassifier for fast (~5ms) offline intent classification.
Supports English and Hindi/Hinglish.
"""

import os
import json
import pickle
from typing import Tuple, Optional

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import SGDClassifier
from sklearn.pipeline import Pipeline
from sklearn.calibration import CalibratedClassifierCV
import numpy as np

from .logger import get_logger

logger = get_logger(__name__)


class IntentClassifier:
    """
    Two-tier intent classification:
    - Tier 1 (this class): Fast local classifier (~5ms, offline)
    - Tier 2 (Gemini API): Fallback for low-confidence predictions
    
    Trained on bilingual (English + Hindi) examples from training_data.json.
    Uses TF-IDF features with character n-grams for language-agnostic matching.
    """
    
    INTENTS = ["create_event", "read_events", "update_event", "delete_event", "general_conversation"]
    MODEL_FILENAME = "intent_model.pkl"
    
    def __init__(self, training_data_path: str = None, model_path: str = None):
        """
        Initialize the intent classifier.
        
        Args:
            training_data_path: Path to training_data.json
            model_path: Path to save/load the trained model
        """
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.training_data_path = training_data_path or os.path.join(base_dir, "training_data.json")
        self.model_path = model_path or os.path.join(base_dir, self.MODEL_FILENAME)
        
        self.pipeline: Optional[Pipeline] = None
        self._load_or_train()
    
    def _load_or_train(self):
        """Load a pre-trained model or train a new one."""
        if os.path.exists(self.model_path):
            try:
                with open(self.model_path, 'rb') as f:
                    self.pipeline = pickle.load(f)
                logger.info(f"Intent classifier loaded from {self.model_path}")
                return
            except Exception as e:
                logger.warning(f"Failed to load model: {e}. Retraining...")
        
        self._train()
    
    def _train(self):
        """Train the classifier from training_data.json."""
        if not os.path.exists(self.training_data_path):
            logger.error(f"Training data not found at {self.training_data_path}")
            raise FileNotFoundError(f"Training data not found: {self.training_data_path}")
        
        with open(self.training_data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Build training set
        texts = []
        labels = []
        for intent, examples in data.items():
            for example in examples:
                texts.append(example.lower().strip())
                labels.append(intent)
        
        logger.info(f"Training intent classifier on {len(texts)} examples across {len(data)} intents")
        
        # Build pipeline: TF-IDF → Calibrated SGD
        # Use char_wb n-grams alongside word n-grams for Hindi/transliteration robustness
        self.pipeline = Pipeline([
            ('tfidf', TfidfVectorizer(
                ngram_range=(1, 3),
                analyzer='word',
                sublinear_tf=True,
                max_features=5000,
                strip_accents='unicode',
            )),
            ('clf', CalibratedClassifierCV(
                SGDClassifier(
                    loss='modified_huber',  # Gives probability estimates
                    alpha=1e-4,
                    max_iter=1000,
                    random_state=42,
                    class_weight='balanced',
                ),
                cv=3,
                method='sigmoid'
            ))
        ])
        
        self.pipeline.fit(texts, labels)
        
        # Save trained model
        try:
            with open(self.model_path, 'wb') as f:
                pickle.dump(self.pipeline, f)
            logger.info(f"Intent classifier saved to {self.model_path}")
        except Exception as e:
            logger.warning(f"Failed to save model: {e}")
        
        # Log training accuracy
        train_accuracy = self.pipeline.score(texts, labels)
        logger.info(f"Training accuracy: {train_accuracy:.3f}")
    
    def classify(self, text: str) -> Tuple[str, float]:
        """
        Classify user input into an intent.
        
        Args:
            text: User's natural language input
            
        Returns:
            Tuple of (intent_name, confidence_score)
            confidence_score is between 0.0 and 1.0
        """
        if self.pipeline is None:
            raise RuntimeError("Intent classifier not trained")
        
        cleaned = text.lower().strip()
        
        # Get probability predictions
        probs = self.pipeline.predict_proba([cleaned])[0]
        classes = self.pipeline.classes_
        
        # Find best class
        best_idx = np.argmax(probs)
        intent = classes[best_idx]
        confidence = probs[best_idx]
        
        logger.debug(f"Intent classification: '{cleaned}' → {intent} ({confidence:.3f})")
        logger.debug(f"All probabilities: {dict(zip(classes, [f'{p:.3f}' for p in probs]))}")
        
        return intent, float(confidence)
    
    def retrain(self):
        """Force retrain from the latest training data."""
        if os.path.exists(self.model_path):
            os.remove(self.model_path)
        self._train()
        logger.info("Intent classifier retrained")
