import numpy as np

np.random.seed(1234)

import torch
import torchaudio
import librosa
from torchaudio.transforms import MelSpectrogram

from utils import parse_filelist


class AudioDataset(torch.utils.data.Dataset):
    """
    Provides dataset management for given filelist.
    """

    def __init__(self, config, training=True):
        super(AudioDataset, self).__init__()
        self.config = config
        self.hop_length = config.data_config.hop_length
        self.training = training

        if self.training:
            self.segment_length = config.training_config.segment_length
        self.sample_rate = config.data_config.sample_rate

        self.filelist_path = (
            config.training_config.train_filelist_path
            if self.training
            else config.training_config.test_filelist_path
        )
        self.audio_paths = parse_filelist(self.filelist_path)

    def load_audio_to_torch(self, audio_path):
        audio, sample_rate = torchaudio.load(audio_path)
        # To ensure upsampling/downsampling will be processed in a right way for full signals
        if not self.training:
            p = (
                audio.shape[-1] // self.hop_length + 1
            ) * self.hop_length - audio.shape[-1]
            audio = torch.nn.functional.pad(audio, (0, p), mode="constant").data
        return audio.squeeze(), sample_rate

    def __getitem__(self, index):
        audio_path = self.audio_paths[index]
        audio, sample_rate = self.load_audio_to_torch(audio_path)

        assert (
            sample_rate == self.sample_rate
        ), f"""Got path to audio of sampling rate {sample_rate}, \
                but required {self.sample_rate} according config."""

        if not self.training:  # If test
            return audio
        # Take segment of audio for training
        if audio.shape[-1] > self.segment_length:
            max_audio_start = audio.shape[-1] - self.segment_length
            audio_start = np.random.randint(0, max_audio_start)
            segment = audio[audio_start: audio_start + self.segment_length]
        else:
            segment = torch.nn.functional.pad(
                audio, (0, self.segment_length - audio.shape[-1]), "constant"
            ).data
        return segment

    def __len__(self):
        return len(self.audio_paths)

    def sample_test_batch(self, size):
        idx = np.random.choice(range(len(self)), size=size, replace=False)
        test_batch = []
        for index in idx:
            test_batch.append(self.__getitem__(index))
        return test_batch


class MelSpectrogramFixedOriginal(torch.nn.Module):
    """In order to remove padding of torchaudio package + add log10 scale."""

    def __init__(self, **kwargs):
        super(MelSpectrogramFixedOriginal, self).__init__()
        self.torchaudio_backend = MelSpectrogram(**kwargs)

    def forward(self, x):
        outputs = self.torchaudio_backend(x).log10()
        mask = torch.isinf(outputs)
        outputs[mask] = 0
        return outputs[..., :-1]


class MelSpectrogramFixed(torch.nn.Module):
    def __init__(
        self,
        sample_rate=22050,
        n_fft=1024,
        hop_length=256,
        win_length=1024,
        window=torch.hann_window,
        n_mels=80,
        f_min=80,
        f_max=7600,
        eps=1e-10,
    ):
        super().__init__()
        self.eps = eps
        self.f_min = 0 if f_min is None else f_min
        self.f_max = sample_rate / 2 if f_max is None else f_max
        self.n_mels = n_mels
        self.win_length = win_length
        self.hop_length = hop_length
        self.n_fft = n_fft
        self.sample_rate = sample_rate

        self.register_buffer('window', window(win_length))
        self.register_buffer(
            'mel_basis',
            torch.from_numpy(
                librosa.filters.mel(
                    self.sample_rate, self.n_fft, self.n_mels, self.f_min, self.f_max
                ).T
            )
        )

    def forward(self, x):
        # (batch × n_fft × time × 2)
        x_stft = (
            torch.stft(
                x,
                n_fft=self.n_fft,
                hop_length=self.hop_length,
                win_length=self.win_length,
                window=self.window,
                pad_mode="reflect",
            )
            ** 2
        )
        # (batch × n_fft × time)
        spc = (x_stft[..., 0] + x_stft[..., 1]).sqrt().float()
        return torch.matmul(spc.transpose(-1, -2), self.mel_basis).clamp(min=self.eps).log10().transpose(-1, -2)[..., :-1]
