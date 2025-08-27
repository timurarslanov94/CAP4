"""
Общие типы для аудио модулей.
"""

from dataclasses import dataclass
import numpy as np


@dataclass
class AudioFrame:
    """Фрейм аудио данных"""
    data: np.ndarray
    sample_rate: int
    timestamp: float