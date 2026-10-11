# src/downloader.py
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform.startswith("win")

FALLBACK_VIDEO_QUALITIES = ["1080p", "720p", "480p", "360p"]
PROGRESS_RE = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")
FORMATS_RE = re.compile(r"Downloading \d+ format\(s\): (\S+)")

# Resultados possíveis de um download
RESULT_OK = "ok"
RESULT_ERROR = "error"
RESULT_CANCELLED = "cancelled"


class Downloader:
    def __init__(self, progress_callback=None, log_callback=None):
        self.progress_callback = progress_callback
        self.log_callback = log_callback

        # Caminho dos executáveis
        self.base_dir = Path(__file__).parent.parent
        self.tools_dir = self.base_dir / "tools"
        self.ytdlp_path = self._find_tool("yt-dlp")
        self.ffmpeg_path = self._find_tool("ffmpeg")

        self.missing_tools = []
        self._process = None
        self._process_lock = threading.Lock()
        self._cancel_event = threading.Event()

        self._check_executables()

    # ------------------------------------------------------------------
    # Setup / utilidades
    # ------------------------------------------------------------------
    def _find_tool(self, name):
        """Procura em tools/ primeiro e, se não achar, no PATH do sistema."""
        exe_name = f"{name}.exe" if IS_WINDOWS else name
        local = self.tools_dir / exe_name
        if local.exists():
            return local

        found = shutil.which(name)
        return Path(found) if found else local

    def _check_executables(self):
        self.missing_tools = []
        for path in (self.ytdlp_path, self.ffmpeg_path):
            if path.exists():
                logger.info("Encontrado: %s", path)
            else:
                logger.error("Não encontrado: %s", path)
                self.missing_tools.append(path.name)

    @staticmethod
    def _hidden_window_kwargs():
        """Evita que uma janela de console pisque a cada subprocess (Windows)."""
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
    def _last_error_line(text):
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        for line in reversed(lines):
            if line.startswith("ERROR"):
                return line[:200]
        return lines[-1][:200] if lines else ""

    @staticmethod
    def sanitize_filename(name, max_length=150):
        """Remove caracteres inválidos para nomes de arquivo (Windows/Linux)."""
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name or "")
        name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
        if len(name) > max_length:
            name = name[:max_length].rstrip(". ")
        return name

    def log(self, message):
        logger.info(message)
        if self.log_callback:
            self.log_callback(message)

    def update_progress(self, value):
        if self.progress_callback:
            self.progress_callback(value)

    # ------------------------------------------------------------------
    # Busca de informações
    # ------------------------------------------------------------------
    @staticmethod
    def _qualities_from_info(data):
        """Extrai as resoluções de vídeo do JSON do yt-dlp (campo 'formats')."""
        heights = set()
        for fmt in data.get("formats") or []:
            height = fmt.get("height")
            if fmt.get("vcodec") != "none" and isinstance(height, int) and height > 0:
                heights.add(height)

        videos = [f"{h}p" for h in sorted(heights, reverse=True)]
        return {
            "title": data.get("title") or "Vídeo desconhecido",
            "video": videos or list(FALLBACK_VIDEO_QUALITIES),
            "ok": bool(videos),
        }

    def fetch_playlist_info(self, url):
        """Detecta se é playlist e retorna informações dos vídeos.

        Para vídeo único, já devolve também as qualidades (chave 'qualities')
        quando o yt-dlp as informa, evitando uma segunda chamada.
        """
        cmd = [
            str(self.ytdlp_path),
            "--flat-playlist",
            "--dump-json",
            "--no-warnings",
            url,
        ]

        try:
            result = self._run_quiet(cmd, timeout=90)
        except subprocess.TimeoutExpired:
            return {"type": "error", "message": "Timeout ao buscar o link"}
        except FileNotFoundError:
            return {"type": "error", "message": f"yt-dlp não encontrado em {self.ytdlp_path}"}
        except Exception as e:
            logger.exception("Erro ao buscar playlist")
            return {"type": "error", "message": f"Erro: {e}"}

        # Playlists com vídeos indisponíveis retornam código != 0 mas ainda trazem dados
        if result.returncode != 0 and not result.stdout.strip():
            message = self._last_error_line(result.stderr) or "Erro ao buscar o link"
            return {"type": "error", "message": message}

        entries = []
        playlist_title = None
        first_data = None

        for line in result.stdout.strip().splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            if first_data is None:
                first_data = data

            playlist_title = playlist_title or data.get("playlist_title") or data.get("playlist")

            video_id = data.get("id", "")
            entries.append({
                "id": video_id,
                "title": data.get("title") or "Vídeo sem título",
                "url": data.get("url")
                or data.get("webpage_url")
                or f"https://www.youtube.com/watch?v={video_id}",
            })

        if len(entries) > 1:
            return {
                "type": "playlist",
                "title": playlist_title or "Playlist",
                "count": len(entries),
                "entries": entries,
            }

        if len(entries) == 1:
            qualities = None
            if first_data and first_data.get("formats"):
                qualities = self._qualities_from_info(first_data)
            return {
                "type": "video",
                "title": entries[0]["title"],
                "url": entries[0]["url"],
                "qualities": qualities,
            }

        return {"type": "error", "message": "Nenhum vídeo encontrado"}

    def fetch_available_qualities(self, url):
        """Busca título e resoluções disponíveis de um vídeo (uma única chamada)."""
        fallback = {
            "title": "Vídeo desconhecido",
            "video": list(FALLBACK_VIDEO_QUALITIES),
            "ok": False,
        }

        cmd = [
            str(self.ytdlp_path),
            "--dump-json",
            "--no-playlist",
            "--no-warnings",
            url,
        ]

        try:
            result = self._run_quiet(cmd, timeout=60)
        except subprocess.TimeoutExpired:
            logger.warning("Timeout ao buscar qualidades")
            return fallback
        except Exception:
            logger.exception("Erro ao buscar qualidades")
            return fallback

        if result.returncode != 0 or not result.stdout.strip():
            logger.warning("yt-dlp não retornou dados: %s", self._last_error_line(result.stderr))
            return fallback

        try:
            first_line = next(l for l in result.stdout.splitlines() if l.strip())
            data = json.loads(first_line)
        except (StopIteration, json.JSONDecodeError):
            return fallback

        return self._qualities_from_info(data)

    # ------------------------------------------------------------------
    # Nomes de arquivo
    # ------------------------------------------------------------------
    def _get_unique_base(self, output_path, base_name, extension):
        """Retorna um nome-base que não sobrescreve arquivos existentes."""
        candidate = base_name
        counter = 1
        while os.path.exists(os.path.join(output_path, f"{candidate}.{extension}")):
            candidate = f"{base_name} (copia {counter})"
            counter += 1

        if candidate != base_name:
            self.log(f"⚠️ Arquivo já existe, salvando como: {candidate}.{extension}")
        return candidate

    def _output_args(self, output_path, custom_name, extension):
        """Monta -P (pasta) e -o (template do nome).

        A pasta vai em -P para que '%' no caminho não seja interpretado como
        template; no nome customizado o '%' é escapado.
        """
        if custom_name:
            base = self._get_unique_base(output_path, custom_name, extension)
            template = base.replace("%", "%%") + ".%(ext)s"
        else:
            template = "%(title)s.%(ext)s"
        return ["-P", output_path, "-o", template]

    def _ffmpeg_args(self):
        if self.ffmpeg_path.exists():
            return ["--ffmpeg-location", str(self.ffmpeg_path.parent)]
        return []

    # ------------------------------------------------------------------
    # Downloads
    # ------------------------------------------------------------------
    def download_mp3(self, url, output_path, quality="320", custom_name=None):
        """Baixa áudio em MP3 com bitrate específico (kbps)."""
        self.log(f"🎵 Baixando MP3 {quality}kbps...")

        cmd = [
            str(self.ytdlp_path),
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", str(quality),  # valores >= 10 são tratados como kbps
            *self._ffmpeg_args(),
            *self._output_args(output_path, custom_name, "mp3"),
            "--no-playlist",
            "--no-warnings",
            "--newline",
            url,
        ]

        return self._run_command(cmd, expected_streams=1)

    def download_mp4(self, url, output_path, quality="720", custom_name=None):
        """Baixa vídeo em MP4 limitado a uma resolução."""
        height = str(quality).replace("p", "")
        self.log(f"🎬 Baixando MP4 até {height}p...")

        cmd = [
            str(self.ytdlp_path),
            "-f", f"bestvideo[height<={height}]+bestaudio/best[height<={height}]",
            "--merge-output-format", "mp4",
            *self._ffmpeg_args(),
            *self._output_args(output_path, custom_name, "mp4"),
            "--no-playlist",
            "--no-warnings",
            "--newline",
            url,
        ]

        return self._run_command(cmd, expected_streams=2)

    def _run_command(self, cmd, expected_streams=1):
        """Executa o yt-dlp e devolve RESULT_OK, RESULT_ERROR ou RESULT_CANCELLED."""
        process = None
        try:
            logger.info("Comando: %s", " ".join(cmd))

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                **self._hidden_window_kwargs(),
            )
            with self._process_lock:
                self._process = process

            output_lines = []
            stream_index = 0  # qual stream (vídeo/áudio) está sendo baixado

            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                output_lines.append(line)

                if "[download] Destination:" in line:
                    stream_index += 1

                formats_match = FORMATS_RE.search(line)
                if formats_match:
                    expected_streams = formats_match.group(1).count("+") + 1

                progress_match = PROGRESS_RE.search(line)
                if progress_match:
                    percent = float(progress_match.group(1))
                    index = max(stream_index, 1)
                    overall = (index - 1 + percent / 100) / expected_streams
                    self.update_progress(min(overall, 0.99))
                else:
                    self.log(line)

            process.wait()

            if self._cancel_event.is_set():
                self.log("⏹ Download cancelado.")
                return RESULT_CANCELLED

            if process.returncode == 0:
                self.log("✅ Download concluído com sucesso!")
                self.update_progress(1.0)
                return RESULT_OK

            self.log(f"❌ Erro no download (código: {process.returncode})")
            for line in output_lines[-5:]:
                self.log(f"   {line}")
            return RESULT_ERROR

        except FileNotFoundError as e:
            self.log(f"❌ Arquivo não encontrado: {e}")
            return RESULT_ERROR
        except Exception as e:
            logger.exception("Erro ao executar o yt-dlp")
            self.log(f"❌ Erro: {e}")
            return RESULT_ERROR
        finally:
            with self._process_lock:
                self._process = None

    def cancel(self):
        """Cancela o download em andamento (mata o yt-dlp e o ffmpeg filho)."""
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

    def start_download(self, url, format_type, quality, output_path,
                       custom_name=None, done_callback=None):
        """Inicia o download em uma thread.

        done_callback(result) é chamado na thread de download com
        RESULT_OK, RESULT_ERROR ou RESULT_CANCELLED.
        """
        self._cancel_event.clear()

        def download_thread():
            result = RESULT_ERROR
            try:
                os.makedirs(output_path, exist_ok=True)

                quality_num = quality.replace(" kbps", "").replace("p", "").strip()

                if format_type == "mp3":
                    result = self.download_mp3(url, output_path, quality_num, custom_name)
                else:
                    result = self.download_mp4(url, output_path, quality_num, custom_name)

                if result == RESULT_OK:
                    self.log(f"📁 Arquivo salvo em: {output_path}")
            except Exception as e:
                logger.exception("Erro na thread de download")
                self.log(f"❌ Erro na thread: {e}")
            finally:
                if done_callback:
                    done_callback(result)

        threading.Thread(target=download_thread, daemon=True).start()

    # ------------------------------------------------------------------
    # Manutenção
    # ------------------------------------------------------------------
    def update_ytdlp(self):
        """Atualiza o yt-dlp (yt-dlp -U). Retorna (sucesso, saída)."""
        try:
            result = self._run_quiet([str(self.ytdlp_path), "-U"], timeout=120)
        except subprocess.TimeoutExpired:
            return False, "Timeout ao tentar atualizar o yt-dlp."
        except Exception as e:
            return False, str(e)

        output = f"{result.stdout}\n{result.stderr}".strip()
        return result.returncode == 0, output or "Sem saída do yt-dlp."
