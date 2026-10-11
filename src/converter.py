# src/converter.py
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform.startswith("win")

# Resultados
RESULT_OK = "ok"
RESULT_ERROR = "error"
RESULT_CANCELLED = "cancelled"

# Categorias
CAT_AUDIO_TO_AUDIO = "audio_to_audio"
CAT_VIDEO_TO_VIDEO = "video_to_video"
CAT_VIDEO_TO_AUDIO = "video_to_audio"
CAT_VIDEO_TO_GIF = "video_to_gif"
CAT_CUT = "cut"

CATEGORY_LABELS = {
    CAT_AUDIO_TO_AUDIO: "🎵 Áudio → Áudio",
    CAT_VIDEO_TO_VIDEO: "🎬 Vídeo → Vídeo",
    CAT_VIDEO_TO_AUDIO: "🎥 Vídeo → Áudio",
    CAT_VIDEO_TO_GIF: "🎞️ Vídeo → GIF",
    CAT_CUT: "✂️ Cortar trecho",
}

# Formatos de áudio (saída)
AUDIO_FORMATS = {
    "MP3":  {"ext": "mp3",  "codec": "libmp3lame", "has_bitrate": True},
    "WAV":  {"ext": "wav",  "codec": "pcm_s16le",  "has_bitrate": False},
    "FLAC": {"ext": "flac", "codec": "flac",       "has_bitrate": False},
    "AAC":  {"ext": "m4a",  "codec": "aac",        "has_bitrate": True},
    "OGG":  {"ext": "ogg",  "codec": "libvorbis",  "has_bitrate": True},
    "OPUS": {"ext": "opus", "codec": "libopus",    "has_bitrate": True},
}

# Formatos de vídeo (saída)
VIDEO_FORMATS = {
    "MP4":    {"ext": "mp4",  "vcodec": "libx264",    "acodec": "aac",       "type": "crf"},
    "MKV":    {"ext": "mkv",  "vcodec": "libx264",    "acodec": "aac",       "type": "crf"},
    "AVI":    {"ext": "avi",  "vcodec": "libx264",    "acodec": "ac3",       "type": "crf"},
    "MOV":    {"ext": "mov",  "vcodec": "libx264",    "acodec": "aac",       "type": "crf"},
    "WEBM":   {"ext": "webm", "vcodec": "libvpx-vp9", "acodec": "libopus",   "type": "vp9"},
    "MPEG-2": {"ext": "ts",   "vcodec": "mpeg2video", "acodec": "mp2",       "type": "bitrate"},
    "FLV":    {"ext": "flv",  "vcodec": "libx264",    "acodec": "aac",       "type": "crf"},
}

# Vídeo → Áudio
VIDEO_TO_AUDIO_FORMATS = {
    "MP3":  {"ext": "mp3",  "codec": "libmp3lame", "has_bitrate": True},
    "WAV":  {"ext": "wav",  "codec": "pcm_s16le",  "has_bitrate": False},
    "FLAC": {"ext": "flac", "codec": "flac",       "has_bitrate": False},
    "AAC":  {"ext": "m4a",  "codec": "aac",        "has_bitrate": True},
}

# Opções
AUDIO_BITRATES = ["320", "256", "192", "128", "96", "64"]
VIDEO_RESOLUTIONS = ["Original", "1080p", "720p", "480p", "360p"]
VIDEO_QUALITIES = ["Alta (CRF 18)", "Média (CRF 23)", "Baixa (CRF 28)"]
MPEG2_BITRATES = ["2M", "5M", "8M", "15M"]
GIF_FPS = ["15", "10", "5"]
GIF_WIDTHS = ["480", "320", "240"]

# Extensões
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".opus", ".wma"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".ts", ".m4v", ".wmv", ".mpg", ".mpeg"}
ALL_MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS

# HH:MM:SS, MM:SS ou segundos (aceita decimais no último campo)
TIME_RE = re.compile(r"^\d+(?::\d{1,2}){0,2}(?:\.\d+)?$")


class Converter:
    def __init__(self, progress_callback=None, log_callback=None):
        self.progress_callback = progress_callback
        self.log_callback = log_callback

        self.base_dir = Path(__file__).parent.parent
        self.tools_dir = self.base_dir / "tools"
        self.ffmpeg_path = self._find_tool("ffmpeg")
        self.ffprobe_path = self._find_tool("ffprobe")
        self.missing_tools = []

        self._process = None
        self._process_lock = threading.Lock()
        self._cancel_event = threading.Event()

        self._check_executables()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    def _find_tool(self, name):
        exe_name = f"{name}.exe" if IS_WINDOWS else name
        local = self.tools_dir / exe_name
        if local.exists():
            return local
        found = shutil.which(name)
        return Path(found) if found else local

    def _check_executables(self):
        self.missing_tools = []
        for path in (self.ffmpeg_path, self.ffprobe_path):
            if path.exists():
                logger.info("Encontrado: %s", path)
            else:
                logger.error("Não encontrado: %s", path)
                self.missing_tools.append(path.name)

    @staticmethod
    def _hidden_window_kwargs():
        if IS_WINDOWS:
            return {"creationflags": subprocess.CREATE_NO_WINDOW}
        return {}

    def _run_quiet(self, cmd, timeout):
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            **self._hidden_window_kwargs(),
        )

    @staticmethod
    def sanitize_filename(name, max_length=150):
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name or "")
        name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
        if len(name) > max_length:
            name = name[:max_length].rstrip(". ")
        return name

    @staticmethod
    def parse_time(text):
        """Converte 'HH:MM:SS', 'MM:SS' ou 'SS' em segundos. Retorna None se inválido."""
        text = (text or "").strip()
        if not TIME_RE.match(text):
            return None

        parts = text.split(":")
        # minutos e segundos (campos que não são o primeiro) precisam ser < 60
        for part in parts[1:]:
            if float(part) >= 60:
                return None

        seconds = 0.0
        for part in parts:
            seconds = seconds * 60 + float(part)
        return seconds

    def log(self, message):
        logger.info(message)
        if self.log_callback:
            self.log_callback(message)

    def update_progress(self, value):
        if self.progress_callback:
            self.progress_callback(value)

    # ------------------------------------------------------------------
    # Probe (ffprobe)
    # ------------------------------------------------------------------
    def probe_file(self, path):
        """Retorna info do arquivo via ffprobe."""
        if not os.path.exists(path):
            return {"error": "Arquivo não encontrado"}

        cmd = [
            str(self.ffprobe_path),
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            path,
        ]

        try:
            result = self._run_quiet(cmd, timeout=30)
        except subprocess.TimeoutExpired:
            return {"error": "Timeout ao ler arquivo"}
        except Exception as e:
            return {"error": str(e)}

        if result.returncode != 0:
            return {"error": "ffprobe falhou"}

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"error": "Resposta inválida do ffprobe"}

        info = {
            "type": "unknown",
            "duration": 0.0,
            "size": 0,
            "video_codec": None,
            "audio_codec": None,
            "width": None,
            "height": None,
            "bitrate": 0,
        }

        fmt = data.get("format") or {}
        try:
            info["duration"] = float(fmt.get("duration") or 0)
        except (TypeError, ValueError):
            pass
        try:
            info["size"] = int(fmt.get("size") or 0)
        except (TypeError, ValueError):
            pass
        try:
            info["bitrate"] = int(fmt.get("bit_rate") or 0)
        except (TypeError, ValueError):
            pass

        has_video = False
        has_audio = False
        for stream in data.get("streams") or []:
            codec_type = stream.get("codec_type")
            disposition = stream.get("disposition") or {}

            if codec_type == "video":
                # Capa de álbum embutida em MP3/M4A não é um vídeo de verdade
                if disposition.get("attached_pic"):
                    continue
                if not has_video:
                    has_video = True
                    info["video_codec"] = stream.get("codec_name")
                    try:
                        info["width"] = int(stream.get("width") or 0) or None
                        info["height"] = int(stream.get("height") or 0) or None
                    except (TypeError, ValueError):
                        pass
            elif codec_type == "audio" and not has_audio:
                has_audio = True
                info["audio_codec"] = stream.get("codec_name")

        if has_video:
            info["type"] = "video"
        elif has_audio:
            info["type"] = "audio"

        return info

    # ------------------------------------------------------------------
    # Nomes de arquivo
    # ------------------------------------------------------------------
    def _get_unique_path(self, output_path, base_name, extension):
        candidate = base_name
        counter = 1
        full = os.path.join(output_path, f"{candidate}.{extension}")
        while os.path.exists(full):
            candidate = f"{base_name} (copia {counter})"
            full = os.path.join(output_path, f"{candidate}.{extension}")
            counter += 1
        if candidate != base_name:
            self.log(f"⚠️ Arquivo já existe, salvando como: {candidate}.{extension}")
        return full

    def _build_output_path(self, input_path, output_path, custom_base, index, extension):
        if custom_base:
            base_name = f"{custom_base}_{index:03d}"
        else:
            base_name = Path(input_path).stem
        base_name = self.sanitize_filename(base_name)
        return self._get_unique_path(output_path, base_name, extension)

    # ------------------------------------------------------------------
    # Comandos ffmpeg
    # ------------------------------------------------------------------
    def _base_cmd(self):
        # -loglevel error: o stderr só traz o que importa (erros reais)
        return [str(self.ffmpeg_path), "-y", "-hide_banner", "-loglevel", "error"]

    @staticmethod
    def _progress_args():
        return ["-progress", "pipe:1", "-nostats"]

    def _build_audio_to_audio_cmd(self, input_path, output_path, format_name, bitrate):
        fmt = AUDIO_FORMATS[format_name]
        cmd = self._base_cmd() + ["-i", input_path, "-vn", "-acodec", fmt["codec"]]
        if fmt["has_bitrate"] and bitrate:
            cmd += ["-b:a", f"{bitrate}k"]
        cmd += self._progress_args() + [output_path]
        return cmd

    @staticmethod
    def _video_filters(resolution, source_info):
        """Filtro de escala: nunca amplia o vídeo e garante dimensões pares."""
        source_info = source_info or {}
        src_w = source_info.get("width")
        src_h = source_info.get("height")

        if resolution and resolution != "Original":
            try:
                target = int(resolution.replace("p", ""))
            except ValueError:
                target = None
            # Só reduz: se o vídeo já é menor ou igual, mantém o tamanho
            if target and (not src_h or src_h > target):
                return f"scale=-2:{target}"

        # libx264 com yuv420p exige largura e altura pares
        if src_w and src_h and (src_w % 2 or src_h % 2):
            return "scale=trunc(iw/2)*2:trunc(ih/2)*2"
        return None

    def _build_video_to_video_cmd(self, input_path, output_path, format_name,
                                   resolution, quality, mpeg2_bitrate, source_info=None):
        fmt = VIDEO_FORMATS[format_name]
        cmd = self._base_cmd() + ["-i", input_path]

        video_filter = self._video_filters(resolution, source_info)
        if video_filter:
            cmd += ["-vf", video_filter]

        if fmt["type"] == "crf":
            crf = self._crf_from_quality(quality)
            cmd += ["-c:v", fmt["vcodec"], "-crf", str(crf)]
        elif fmt["type"] == "vp9":
            crf = self._crf_from_quality(quality)
            cmd += ["-c:v", fmt["vcodec"], "-crf", str(crf), "-b:v", "0",
                    "-row-mt", "1", "-cpu-used", "2"]
        elif fmt["type"] == "bitrate":
            cmd += ["-c:v", fmt["vcodec"], "-b:v", f"{mpeg2_bitrate}"]

        # yuv420p: compatível com celulares, navegadores e a maioria dos players
        cmd += ["-pix_fmt", "yuv420p"]

        cmd += ["-c:a", fmt["acodec"]]
        if fmt["acodec"] == "aac":
            cmd += ["-b:a", "192k"]

        if fmt["ext"] in ("mp4", "mov"):
            cmd += ["-movflags", "+faststart"]

        cmd += self._progress_args() + [output_path]
        return cmd

    @staticmethod
    def _crf_from_quality(quality):
        if "18" in str(quality):
            return 18
        if "28" in str(quality):
            return 28
        return 23

    def _build_video_to_audio_cmd(self, input_path, output_path, format_name, bitrate):
        fmt = VIDEO_TO_AUDIO_FORMATS[format_name]
        cmd = self._base_cmd() + ["-i", input_path, "-vn", "-acodec", fmt["codec"]]
        if fmt["has_bitrate"] and bitrate:
            cmd += ["-b:a", f"{bitrate}k"]
        cmd += self._progress_args() + [output_path]
        return cmd

    def _build_video_to_gif_cmd(self, input_path, output_path, fps, width, source_info=None):
        try:
            target_w = int(width)
        except (TypeError, ValueError):
            target_w = 320
        src_w = (source_info or {}).get("width")
        if src_w and src_w < target_w:
            target_w = src_w  # não amplia

        # Paleta própria: cores bem melhores e arquivo menor que o GIF padrão
        video_filter = (
            f"fps={fps},scale={target_w}:-1:flags=lanczos,"
            "split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"
        )
        cmd = self._base_cmd() + ["-i", input_path, "-vf", video_filter, "-loop", "0"]
        cmd += self._progress_args() + [output_path]
        return cmd

    def _build_cut_cmd(self, input_path, output_path, start_s, duration_s, precise=False):
        # -ss antes do -i + -t (duração): o trecho fica exatamente [início, fim]
        cmd = self._base_cmd() + [
            "-ss", f"{start_s:.3f}",
            "-i", input_path,
            "-t", f"{duration_s:.3f}",
        ]
        if not precise:
            # Rápido: sem recodificar (corta no quadro-chave mais próximo)
            cmd += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
        cmd += self._progress_args() + [output_path]
        return cmd

    # ------------------------------------------------------------------
    # Execução
    # ------------------------------------------------------------------
    def _remove_partial(self, path):
        """Apaga a saída incompleta (cancelamento/erro). O caminho é sempre novo,
        então nunca apaga um arquivo que já existia antes da conversão."""
        if not path:
            return
        for _ in range(5):
            try:
                if os.path.exists(path):
                    os.remove(path)
                    logger.info("Arquivo parcial removido: %s", path)
                return
            except OSError:
                time.sleep(0.2)  # o Windows pode demorar a soltar o arquivo
        logger.warning("Não foi possível remover o arquivo parcial: %s", path)

    def _run_ffmpeg(self, cmd, total_duration, output_path=None):
        process = None
        try:
            logger.info("Comando: %s", " ".join(cmd))
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                **self._hidden_window_kwargs(),
            )
            with self._process_lock:
                self._process = process

            stderr_lines = deque(maxlen=30)

            def read_stderr():
                for line in process.stderr:
                    stderr_lines.append(line.strip())

            stderr_thread = threading.Thread(target=read_stderr, daemon=True)
            stderr_thread.start()

            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue

                if line.startswith("out_time_us="):
                    try:
                        us = int(line.split("=")[1])
                        seconds = us / 1_000_000
                        if total_duration > 0:
                            fraction = min(max(seconds, 0) / total_duration, 0.99)
                            self.update_progress(fraction)
                    except (ValueError, IndexError):
                        pass
                elif line.startswith("progress="):
                    if "end" in line:
                        self.update_progress(1.0)

            process.wait()
            stderr_thread.join(timeout=2)

            if self._cancel_event.is_set():
                self.log("⏹ Conversão cancelada.")
                self._remove_partial(output_path)
                return RESULT_CANCELLED

            if process.returncode == 0:
                self.log("✅ Conversão concluída com sucesso!")
                self.update_progress(1.0)
                return RESULT_OK

            self.log(f"❌ Erro na conversão (código: {process.returncode})")
            for line in list(stderr_lines)[-5:]:
                if line:
                    self.log(f"   {line}")
            self._remove_partial(output_path)
            return RESULT_ERROR

        except FileNotFoundError as e:
            self.log(f"❌ ffmpeg não encontrado: {e}")
            return RESULT_ERROR
        except Exception as e:
            logger.exception("Erro ao executar ffmpeg")
            self.log(f"❌ Erro: {e}")
            self._remove_partial(output_path)
            return RESULT_ERROR
        finally:
            with self._process_lock:
                self._process = None

    def cancel(self):
        self._cancel_event.set()
        with self._process_lock:
            process = self._process
        if process is not None and process.poll() is None:
            try:
                if IS_WINDOWS:
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                        capture_output=True,
                        **self._hidden_window_kwargs(),
                    )
                else:
                    process.terminate()
            except Exception:
                logger.exception("Erro ao cancelar o processo")

    # ------------------------------------------------------------------
    # Conversões
    # ------------------------------------------------------------------
    def _get_duration(self, path):
        info = self.probe_file(path)
        return info.get("duration", 0.0) or 0.0

    def _resolve_duration(self, path, file_info):
        """Usa a duração já lida na seleção; só chama o ffprobe se faltar."""
        duration = (file_info or {}).get("duration") or 0
        return duration if duration > 0 else self._get_duration(path)

    def convert_audio_to_audio(self, input_path, output_path, format_name,
                                bitrate, custom_base, index, file_info=None):
        fmt = AUDIO_FORMATS[format_name]
        final_path = self._build_output_path(input_path, output_path, custom_base, index, fmt["ext"])
        self.log(f"🎵 Convertendo para {format_name}...")
        cmd = self._build_audio_to_audio_cmd(input_path, final_path, format_name, bitrate)
        duration = self._resolve_duration(input_path, file_info)
        return self._run_ffmpeg(cmd, duration, final_path), final_path

    def convert_video_to_video(self, input_path, output_path, format_name,
                                resolution, quality, mpeg2_bitrate, custom_base, index,
                                file_info=None):
        fmt = VIDEO_FORMATS[format_name]
        final_path = self._build_output_path(input_path, output_path, custom_base, index, fmt["ext"])
        self.log(f"🎬 Convertendo para {format_name}...")
        cmd = self._build_video_to_video_cmd(input_path, final_path, format_name,
                                              resolution, quality, mpeg2_bitrate, file_info)
        duration = self._resolve_duration(input_path, file_info)
        return self._run_ffmpeg(cmd, duration, final_path), final_path

    def extract_audio_from_video(self, input_path, output_path, format_name,
                                  bitrate, custom_base, index, file_info=None):
        fmt = VIDEO_TO_AUDIO_FORMATS[format_name]
        final_path = self._build_output_path(input_path, output_path, custom_base, index, fmt["ext"])
        self.log(f"🎥 Extraindo áudio para {format_name}...")
        cmd = self._build_video_to_audio_cmd(input_path, final_path, format_name, bitrate)
        duration = self._resolve_duration(input_path, file_info)
        return self._run_ffmpeg(cmd, duration, final_path), final_path

    def convert_video_to_gif(self, input_path, output_path, fps, width,
                              custom_base, index, file_info=None):
        final_path = self._build_output_path(input_path, output_path, custom_base, index, "gif")
        self.log("🎞️ Convertendo para GIF...")
        cmd = self._build_video_to_gif_cmd(input_path, final_path, fps, width, file_info)
        duration = self._resolve_duration(input_path, file_info)
        return self._run_ffmpeg(cmd, duration, final_path), final_path

    def cut_media(self, input_path, output_path, start, end, precise,
                  custom_base, index, file_info=None):
        start_s = self.parse_time(start)
        end_s = self.parse_time(end)
        if start_s is None or end_s is None or end_s <= start_s:
            self.log("❌ Tempos de corte inválidos.")
            return RESULT_ERROR, None

        total = self._resolve_duration(input_path, file_info)
        duration_s = end_s - start_s
        if total > 0:
            if start_s >= total:
                self.log("❌ O início do corte passa da duração do arquivo.")
                return RESULT_ERROR, None
            duration_s = min(duration_s, total - start_s)  # fim além do arquivo: vai até o final

        ext = Path(input_path).suffix.lstrip(".") or "mp4"
        final_path = self._build_output_path(input_path, output_path, custom_base, index, ext)
        mode = "preciso" if precise else "rápido"
        self.log(f"✂️ Cortando trecho {start} → {end} (modo {mode})...")
        cmd = self._build_cut_cmd(input_path, final_path, start_s, duration_s, precise)
        return self._run_ffmpeg(cmd, duration_s, final_path), final_path

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def start_conversion(self, item, done_callback=None):
        """Inicia conversão em thread.
        done_callback(result, final_path) é chamado no final.
        """
        self._cancel_event.clear()

        def conversion_thread():
            result = RESULT_ERROR
            final_path = None
            try:
                os.makedirs(item["output_path"], exist_ok=True)

                cat = item["category"]
                opts = item.get("options") or {}
                custom_base = item.get("custom_base")
                index = item.get("index", 1)
                file_info = item.get("file_info")

                if cat == CAT_AUDIO_TO_AUDIO:
                    result, final_path = self.convert_audio_to_audio(
                        item["input_path"], item["output_path"],
                        opts.get("format", "MP3"),
                        opts.get("bitrate"),
                        custom_base, index, file_info,
                    )
                elif cat == CAT_VIDEO_TO_VIDEO:
                    result, final_path = self.convert_video_to_video(
                        item["input_path"], item["output_path"],
                        opts.get("format", "MP4"),
                        opts.get("resolution"),
                        opts.get("quality"),
                        opts.get("mpeg2_bitrate"),
                        custom_base, index, file_info,
                    )
                elif cat == CAT_VIDEO_TO_AUDIO:
                    result, final_path = self.extract_audio_from_video(
                        item["input_path"], item["output_path"],
                        opts.get("format", "MP3"),
                        opts.get("bitrate"),
                        custom_base, index, file_info,
                    )
                elif cat == CAT_VIDEO_TO_GIF:
                    result, final_path = self.convert_video_to_gif(
                        item["input_path"], item["output_path"],
                        opts.get("fps", "10"),
                        opts.get("width", "320"),
                        custom_base, index, file_info,
                    )
                elif cat == CAT_CUT:
                    result, final_path = self.cut_media(
                        item["input_path"], item["output_path"],
                        opts.get("start", "00:00:00"),
                        opts.get("end", "00:00:30"),
                        opts.get("precise", False),
                        custom_base, index, file_info,
                    )

                if result == RESULT_OK and final_path:
                    self.log(f"📁 Arquivo salvo em: {final_path}")
            except Exception as e:
                logger.exception("Erro na thread de conversão")
                self.log(f"❌ Erro na thread: {e}")
            finally:
                if done_callback:
                    done_callback(result, final_path)

        threading.Thread(target=conversion_thread, daemon=True).start()


def check_compatibility(category, info, options=None):
    """Verifica se um arquivo (info do probe_file) serve para a categoria.

    Retorna (ok, motivo).
    """
    info = info or {}
    kind = info.get("type")

    if category == CAT_AUDIO_TO_AUDIO:
        if kind != "audio":
            return False, "não é um arquivo de áudio"
    elif category in (CAT_VIDEO_TO_VIDEO, CAT_VIDEO_TO_GIF):
        if kind != "video":
            return False, "não é um arquivo de vídeo"
    elif category == CAT_VIDEO_TO_AUDIO:
        if kind != "video":
            return False, "não é um arquivo de vídeo"
        if not info.get("audio_codec"):
            return False, "o vídeo não tem faixa de áudio"
    elif category == CAT_CUT:
        if kind not in ("audio", "video"):
            return False, "formato não reconhecido"
        start_s = Converter.parse_time((options or {}).get("start"))
        duration = info.get("duration") or 0
        if start_s is not None and duration > 0 and start_s >= duration:
            return False, "o início do corte passa da duração do arquivo"

    return True, ""
