import shutil
import subprocess


def play_wav(path):
    if shutil.which("afplay"):
        subprocess.run(
            [
                "afplay",
                str(path)
            ],
            check=True
        )
        return

    if shutil.which("aplay"):
        subprocess.run(
            [
                "aplay",
                str(path)
            ],
            check=True
        )
        return

    import sounddevice as sd
    import soundfile as sf

    audio, samplerate = sf.read(str(path))
    sd.play(audio, samplerate)
    sd.wait()
