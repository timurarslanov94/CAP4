"""
Абстракция для различных типов аудио транспорта между Baresip и Python.
"""

import asyncio
import os
from abc import ABC, abstractmethod
from typing import Optional, AsyncIterator
from dataclasses import dataclass
import struct
import numpy as np
from enum import Enum

import structlog

logger = structlog.get_logger()


class AudioFormat(Enum):
    """Поддерживаемые форматы аудио"""
    PCM_16BIT_8KHZ_MONO = "pcm_8k"  # Для телефонии (baresip)
    PCM_16BIT_16KHZ_MONO = "pcm_16k"  # Для ElevenLabs
    ULAW_8KHZ_MONO = "ulaw_8k"  # G.711 μ-law


@dataclass
class AudioConfig:
    """Конфигурация аудио потока"""
    format: AudioFormat
    chunk_duration_ms: int = 20  # Стандартная длительность чанка для VoIP
    
    @property
    def sample_rate(self) -> int:
        if self.format == AudioFormat.PCM_16BIT_8KHZ_MONO:
            return 8000
        elif self.format == AudioFormat.PCM_16BIT_16KHZ_MONO:
            return 16000
        elif self.format == AudioFormat.ULAW_8KHZ_MONO:
            return 8000
        return 8000
    
    @property
    def chunk_size_bytes(self) -> int:
        """Размер чанка в байтах"""
        samples_per_chunk = int(self.sample_rate * self.chunk_duration_ms / 1000)
        # PCM 16-bit formats use 2 bytes per sample; μ-law uses 1 byte per sample
        if self.format in (AudioFormat.PCM_16BIT_8KHZ_MONO, AudioFormat.PCM_16BIT_16KHZ_MONO):
            return samples_per_chunk * 2
        else:
            return samples_per_chunk
    
    @property
    def chunk_size_samples(self) -> int:
        """Количество сэмплов в чанке"""
        return int(self.sample_rate * self.chunk_duration_ms / 1000)


class AudioTransport(ABC):
    """Базовый класс для аудио транспорта"""
    
    def __init__(self, config: AudioConfig):
        self.config = config
        self._running = False
    
    @abstractmethod
    async def start(self) -> None:
        """Инициализация транспорта"""
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        """Остановка транспорта"""
        pass
    
    @abstractmethod
    async def read_chunk(self) -> Optional[bytes]:
        """Чтение аудио чанка"""
        pass
    
    @abstractmethod
    async def write_chunk(self, data: bytes) -> None:
        """Запись аудио чанка"""
        pass
    
    async def read_stream(self) -> AsyncIterator[bytes]:
        """Генератор для чтения потока"""
        while self._running:
            chunk = await self.read_chunk()
            if chunk:
                yield chunk
            else:
                await asyncio.sleep(0.001)


class NamedPipeTransport(AudioTransport):
    """Транспорт через именованные каналы (FIFO)"""
    
    def __init__(self, config: AudioConfig, 
                 input_pipe: str = "/tmp/baresip_audio_out.pcm",
                 output_pipe: str = "/tmp/baresip_audio_in.pcm"):
        super().__init__(config)
        self.input_pipe = input_pipe  # Откуда читаем (от baresip)
        self.output_pipe = output_pipe  # Куда пишем (в baresip)
        self._input_fd: Optional[int] = None
        self._output_fd: Optional[int] = None
        self._read_task: Optional[asyncio.Task] = None
        self._write_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    
    async def start(self) -> None:
        """Создаём и открываем именованные каналы"""
        # Создаём FIFO если не существуют
        for pipe in [self.input_pipe, self.output_pipe]:
            if not os.path.exists(pipe):
                os.mkfifo(pipe)
                await logger.ainfo(f"Created FIFO pipe: {pipe}")
        
        # Открываем в неблокирующем режиме
        # На macOS используем O_RDWR вместо O_WRONLY для избежания ошибки "Device not configured"
        self._input_fd = os.open(self.input_pipe, os.O_RDONLY | os.O_NONBLOCK)
        self._output_fd = os.open(self.output_pipe, os.O_RDWR | os.O_NONBLOCK)
        
        self._running = True
        await logger.ainfo(
            "Named pipe transport started",
            input_pipe=self.input_pipe,
            output_pipe=self.output_pipe,
            chunk_bytes=self.config.chunk_size_bytes,
            chunk_ms=self.config.chunk_duration_ms,
            sample_rate=self.config.sample_rate,
        )
    
    async def stop(self) -> None:
        """Закрываем каналы"""
        self._running = False
        
        if self._input_fd:
            os.close(self._input_fd)
            self._input_fd = None
        
        if self._output_fd:
            os.close(self._output_fd)
            self._output_fd = None
        
        await logger.ainfo("Named pipe transport stopped")
    
    async def read_chunk(self) -> Optional[bytes]:
        """Читаем чанк из входного канала"""
        if not self._input_fd:
            return None
        
        try:
            # Пытаемся прочитать нужное количество байт
            data = os.read(self._input_fd, self.config.chunk_size_bytes)
            if len(data) == self.config.chunk_size_bytes:
                return data
            # Если прочитали меньше, накапливаем
            buffer = bytearray(data)
            while len(buffer) < self.config.chunk_size_bytes:
                await asyncio.sleep(0.001)
                try:
                    chunk = os.read(self._input_fd, 
                                  self.config.chunk_size_bytes - len(buffer))
                    buffer.extend(chunk)
                except BlockingIOError:
                    continue
            return bytes(buffer)
        except BlockingIOError:
            return None
    
    async def write_chunk(self, data: bytes) -> None:
        """Пишем чанк в выходной канал"""
        if not self._output_fd or not data:
            return
        
        # Убеждаемся, что размер правильный
        if len(data) != self.config.chunk_size_bytes:
            await logger.awarning(f"Chunk size mismatch: {len(data)} != {self.config.chunk_size_bytes}")
            # Паддинг или обрезка
            if len(data) < self.config.chunk_size_bytes:
                data = data + b'\x00' * (self.config.chunk_size_bytes - len(data))
            else:
                data = data[:self.config.chunk_size_bytes]
        
        written = 0
        while written < len(data):
            try:
                n = os.write(self._output_fd, data[written:])
                written += n
            except BlockingIOError:
                await asyncio.sleep(0.001)


class AudioResampler:
    """Ресэмплер для преобразования между форматами"""
    
    @staticmethod
    def resample_pcm(data: bytes, from_rate: int, to_rate: int) -> bytes:
        """Простой ресэмплинг PCM 16-bit"""
        if from_rate == to_rate:
            return data
        
        # Конвертируем в numpy array
        samples = np.frombuffer(data, dtype=np.int16)
        
        # Простая линейная интерполяция
        ratio = to_rate / from_rate
        new_length = int(len(samples) * ratio)
        
        # Индексы для интерполяции
        old_indices = np.arange(len(samples))
        new_indices = np.linspace(0, len(samples) - 1, new_length)
        
        # Интерполяция
        resampled = np.interp(new_indices, old_indices, samples)
        
        return resampled.astype(np.int16).tobytes()
    
    @staticmethod
    def ulaw_to_pcm(data: bytes) -> bytes:
        """Конвертация μ-law в PCM 16-bit"""
        import g711
        return g711.decode_ulaw(data)
    
    @staticmethod
    def pcm_to_ulaw(data: bytes) -> bytes:
        """Конвертация PCM 16-bit в μ-law"""
        import g711
        return g711.encode_ulaw(data)
