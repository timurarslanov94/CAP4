import asyncio
import numpy as np
from typing import Optional, Callable, Any
from dataclasses import dataclass
import queue
import threading

import sounddevice as sd
from scipy.signal import resample_poly
import structlog

from src.infrastructure.audio.audio_types import AudioFrame
from src.core.config import AudioConfig


logger = structlog.get_logger()


class AudioBridge:
    def __init__(self, config: AudioConfig) -> None:
        self.config = config
        self.input_stream: Optional[sd.InputStream] = None
        self.output_stream: Optional[sd.OutputStream] = None
        
        self.input_queue: asyncio.Queue[AudioFrame] = asyncio.Queue()
        self.output_queue: asyncio.Queue[AudioFrame] = asyncio.Queue()
        
        self._running = False
        self._input_callback: Optional[Callable[[AudioFrame], None]] = None
        
    async def start(self) -> None:
        if self._running:
            return
            
        try:
            await self._setup_audio_devices()
            self._running = True
            await logger.ainfo("Audio bridge started")
        except Exception as e:
            await logger.aerror("Failed to start audio bridge", error=str(e))
            raise
    
    async def stop(self) -> None:
        if not self._running:
            return
            
        self._running = False
        
        if self.input_stream:
            self.input_stream.stop()
            self.input_stream.close()
            
        if self.output_stream:
            self.output_stream.stop()
            self.output_stream.close()
            
        await logger.ainfo("Audio bridge stopped")
    
    async def _setup_audio_devices(self) -> None:
        devices = sd.query_devices()
        
        input_device = None
        output_device = None
        
        for idx, device in enumerate(devices):
            if self.config.in_device in device['name']:
                input_device = idx
            if self.config.out_device in device['name']:
                output_device = idx
        
        if input_device is None:
            raise ValueError(f"Input device '{self.config.in_device}' not found")
        if output_device is None:
            raise ValueError(f"Output device '{self.config.out_device}' not found")
        
        def input_callback(indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
            if status:
                logger.warning("Input audio status", status=status)
            
            if self._running and self._input_callback:
                frame = AudioFrame(
                    data=indata.copy().flatten(),
                    sample_rate=self.config.sample_rate_telephony,
                    timestamp=time_info.inputBufferAdcTime
                )
                
                try:
                    self.input_queue.put_nowait(frame)
                except asyncio.QueueFull:
                    logger.warning("Input queue full, dropping frame")
        
        self.input_stream = sd.InputStream(
            device=input_device,
            channels=1,
            samplerate=self.config.sample_rate_telephony,
            dtype=np.int16,
            callback=input_callback,
            blocksize=self.config.chunk_size_telephony
        )
        
        self.output_stream = sd.OutputStream(
            device=output_device,
            channels=1,
            samplerate=self.config.sample_rate_telephony,
            dtype=np.int16,
            blocksize=self.config.chunk_size_telephony
        )
        
        self.input_stream.start()
        self.output_stream.start()
        
        await logger.ainfo(
            "Audio devices configured",
            input_device=devices[input_device]['name'],
            output_device=devices[output_device]['name']
        )
    
    def resample_audio(
        self, 
        audio: np.ndarray, 
        from_rate: int, 
        to_rate: int
    ) -> np.ndarray:
        if from_rate == to_rate:
            return audio
        
        if from_rate == 8000 and to_rate == 16000:
            return resample_poly(audio, 2, 1).astype(np.int16)
        elif from_rate == 16000 and to_rate == 8000:
            return resample_poly(audio, 1, 2).astype(np.int16)
        else:
            ratio = to_rate / from_rate
            new_length = int(len(audio) * ratio)
            return np.interp(
                np.linspace(0, len(audio) - 1, new_length),
                np.arange(len(audio)),
                audio
            ).astype(np.int16)
    
    async def read_frame(self) -> Optional[AudioFrame]:
        try:
            frame = await asyncio.wait_for(
                self.input_queue.get(),
                timeout=0.1
            )
            
            resampled_data = self.resample_audio(
                frame.data,
                self.config.sample_rate_telephony,
                self.config.sample_rate_ai
            )
            
            return AudioFrame(
                data=resampled_data,
                sample_rate=self.config.sample_rate_ai,
                timestamp=frame.timestamp
            )
        except asyncio.TimeoutError:
            return None
    
    async def write_frame(self, frame: AudioFrame) -> None:
        resampled_data = self.resample_audio(
            frame.data,
            frame.sample_rate,
            self.config.sample_rate_telephony
        )
        
        if self.output_stream and self._running:
            self.output_stream.write(resampled_data)
    
    def set_input_callback(self, callback: Callable[[AudioFrame], None]) -> None:
        self._input_callback = callback
    
    async def __aenter__(self) -> "AudioBridge":
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()