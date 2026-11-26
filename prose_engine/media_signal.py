"""Bounded local measurements for selected audio or video ranges."""
import re
from shutil import which
from subprocess import SubprocessError, run


METHOD = 'ffmpeg-quiet-interval-v1'
QUIET = re.compile(r'silence_end: (\d+(?:\.\d+)?)\s*\|\s*silence_duration: (\d+(?:\.\d+)?)')


def interior_pauses(path, start, end):
    """Return quiet intervals on the source clock. Exclude clip-edge silence."""
    ffmpeg = which('ffmpeg')
    if not ffmpeg:
        raise ValueError('FFmpeg is needed to measure a pause in this clip')
    span = (end - start) / 1000
    try:
        result = run([ffmpeg, '-nostdin', '-hide_banner', '-protocol_whitelist', 'file,pipe',
                      '-ss', f'{start / 1000:.3f}', '-i', str(path), '-map', '0:a:0', '-vn', '-sn', '-dn',
                      '-af', f'atrim=duration={span:.3f},asetpts=PTS-STARTPTS,silencedetect=noise=-33dB:d=0.16',
                      '-t', f'{span:.3f}', '-f', 'null', '-'], capture_output=True, timeout=15, check=True)
    except (OSError, SubprocessError) as exc:
        raise ValueError('The selected range does not have readable audio') from exc
    spans = []
    for stop, duration in QUIET.findall(result.stderr.decode('utf-8', 'replace')):
        offset = round((float(stop) - float(duration)) * 1000)
        stop = round(float(stop) * 1000)
        if 40 <= offset < stop <= end - start - 40:
            spans.append({'start_ms': start + offset, 'end_ms': start + stop, 'duration_ms': stop - offset})
    return sorted(spans, key=lambda row: (-row['duration_ms'], row['start_ms']))
