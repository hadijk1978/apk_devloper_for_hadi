import os
import re
import json
import threading
import urllib.request
import flet as ft
import yt_dlp


class MobileDownloader:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "دانلودر یوتیوب و آپارات"
        self.page.rtl = True  # راست‌به‌چپ کامل برای زبان فارسی
        self.page.theme_mode = ft.ThemeMode.LIGHT
        self.page.window.width = 430
        self.page.window.height = 780
        self.page.padding = 16
        self.page.scroll = ft.ScrollMode.AUTO

        self.is_downloading = False
        self.cancel_event = threading.Event()
        self.save_dir = self._get_default_download_dir()

        self._build_ui()

    def _get_default_download_dir(self):
        # تشخیص خودکار مسیر پوشه Downloads در اندروید یا ویندوز
        android_dl = "/storage/emulated/0/Download"
        if os.path.isdir(android_dl):
            return android_dl
        desktop_dl = os.path.join(os.path.expanduser("~"), "Downloads")
        if os.path.isdir(desktop_dl):
            return desktop_dl
        return os.getcwd()

    def _build_ui(self):
        self.url_input = ft.TextField(
            label="لینک ویدیو (یوتیوب، آپارات و...)",
            hint_text="https://...",
            text_direction=ft.TextDirection.LTR,
            border_radius=10,
        )

        self.path_input = ft.TextField(
            label="مسیر ذخیره‌سازی",
            value=self.save_dir,
            text_direction=ft.TextDirection.LTR,
            border_radius=10,
            text_size=12,
        )

        self.type_radio = ft.RadioGroup(
            value="video",
            content=ft.Column([
                ft.Radio(value="video", label="ویدیو همراه با صدا (MP4)"),
                ft.Radio(value="audio", label="فقط فایل صوتی (M4A/MP3)"),
            ]),
        )

        self.quality_dropdown = ft.Dropdown(
            label="حداکثر کیفیت ویدیو",
            value="best",
            options=[
                ft.dropdown.Option("best", "بهترین کیفیت (Best)"),
                ft.dropdown.Option("1080", "1080p (Full HD)"),
                ft.dropdown.Option("720", "720p (HD)"),
                ft.dropdown.Option("480", "480p"),
                ft.dropdown.Option("360", "360p"),
            ],
            border_radius=10,
        )

        self.sub_checkbox = ft.Checkbox(
            label="دانلود زیرنویس فارسی (SRT مجزا)",
            value=True,
        )

        self.start_btn = ft.ElevatedButton(
            text="شروع دانلود",
            icon=ft.Icons.DOWNLOAD,
            on_click=self._on_start,
            expand=True,
            height=45,
        )

        self.cancel_btn = ft.OutlinedButton(
            text="توقف",
            icon=ft.Icons.STOP,
            on_click=self._on_cancel,
            disabled=True,
            height=45,
        )

        self.progress_bar = ft.ProgressBar(value=0, bar_height=8)
        self.status_text = ft.Text("آماده به کار", size=13, weight=ft.FontWeight.BOLD)

        self.log_box = ft.TextField(
            label="گزارش عملیات",
            multiline=True,
            read_only=True,
            min_lines=6,
            max_lines=8,
            text_size=12,
            border_radius=10,
        )

        self.page.add(
            ft.Text("دانلودر جامع ویدیو و زیرنویس", size=20, weight=ft.FontWeight.BOLD),
            self.url_input,
            self.path_input,
            ft.Divider(height=10),
            ft.Text("نوع و کیفیت دانلود:", weight=ft.FontWeight.BOLD),
            self.type_radio,
            self.quality_dropdown,
            self.sub_checkbox,
            ft.Row([self.start_btn, self.cancel_btn], spacing=10),
            ft.Column([self.progress_bar, self.status_text], spacing=5),
            self.log_box,
        )

    def _log(self, msg: str):
        current = self.log_box.value or ""
        self.log_box.value = f"{current}{msg}\n"
        self.page.update()

    def _set_status(self, text: str, progress: float = None):
        self.status_text.value = text
        if progress is not None:
            self.progress_bar.value = max(0.0, min(1.0, progress))
        self.page.update()

    def _set_busy(self, busy: bool):
        self.is_downloading = busy
        self.start_btn.disabled = busy
        self.cancel_btn.disabled = not busy
        self.url_input.disabled = busy
        self.page.update()

    def _on_start(self, e):
        if self.is_downloading:
            return

        url = (self.url_input.value or "").strip()
        out_dir = (self.path_input.value or "").strip()

        if not url:
            self._set_status("خطا: لطفاً لینک ویدیو را وارد کنید.", 0)
            return

        os.makedirs(out_dir, exist_ok=True)
        self.cancel_event.clear()
        self.log_box.value = ""
        self._set_busy(True)
        self._set_status("در حال آماده‌سازی دانلود...", 0)

        threading.Thread(
            target=self._download_worker,
            args=(
                url,
                out_dir,
                self.type_radio.value,
                self.quality_dropdown.value,
                self.sub_checkbox.value,
            ),
            daemon=True,
        ).start()

    def _on_cancel(self, e):
        if self.is_downloading:
            self.cancel_event.set()
            self._log("درخواست توقف ثبت شد...")

    def _resolve_aparat_direct_url(self, url, preferred_height=None):
        match = re.search(r"aparat\.com/v/([a-zA-Z0-9]+)", url)
        if not match:
            return None, None, None

        video_hash = match.group(1)
        api_url = f"https://www.aparat.com/api/fa/v1/video/video/show/videohash/{video_hash}"
        req = urllib.request.Request(
            api_url,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        attributes = data.get("data", {}).get("attributes", {})
        title = attributes.get("title") or f"Aparat_{video_hash}"
        file_link_all = attributes.get("file_link_all", [])

        candidates = []
        for item in file_link_all:
            urls = item.get("urls") or []
            if not urls:
                continue
            profile = str(item.get("profile", ""))
            h_match = re.search(r"(\d+)", profile)
            height = int(h_match.group(1)) if h_match else 0
            candidates.append((height, urls[0]))

        if not candidates:
            return None, None, None

        candidates.sort(key=lambda x: x[0])
        if preferred_height:
            filtered = [c for c in candidates if c[0] <= preferred_height]
            chosen = filtered[-1][1] if filtered else candidates[0][1]
        else:
            chosen = candidates[-1][1]

        return chosen, title, video_hash

    def _download_worker(self, url, out_dir, dl_type, quality, sub_enabled):
        is_aparat = "aparat.com" in url.lower()
        height_limit = int(quality) if quality.isdigit() else None

        def progress_hook(data):
            if self.cancel_event.is_set():
                raise yt_dlp.utils.DownloadError("دانلود متوقف شد.")
            if data.get("status") == "downloading":
                raw_pct = data.get("_percent") or 0
                pct_str = data.get("_percent_str", "0%").strip()
                spd_str = data.get("_speed_str", "").strip()
                self._set_status(f"در حال دانلود: {pct_str} | سرعت: {spd_str}", raw_pct / 100.0)
            elif data.get("status") == "finished":
                self._set_status("دانلود فایل اصلی کامل شد.", 1.0)

        # در اندروید چون ممکن است FFmpeg نباشد، فرمت‌های یکپارچه (صدا+تصویر با هم) در اولویت قرار می‌گیرند
        if dl_type == "video":
            if height_limit:
                fmt = f"best[height<={height_limit}][ext=mp4]/best[height<={height_limit}]/best"
            else:
                fmt = "best[ext=mp4]/best"
        else:
            fmt = "bestaudio[ext=m4a]/bestaudio/best"

        options = {
            "outtmpl": os.path.join(out_dir, "%(title)s [%(id)s].%(ext)s"),
            "format": fmt,
            "noplaylist": True,
            "continuedl": True,
            "progress_hooks": [progress_hook],
            "quiet": True,
        }

        try:
            self._log("مرحله ۱: شروع دریافت فایل...")
            try:
                with yt_dlp.YoutubeDL(options) as ydl:
                    info = ydl.extract_info(url, download=True)
                    expected_file = ydl.prepare_filename(info)
            except Exception:
                if is_aparat:
                    self._log("اتصال مستقیم به API آپارات...")
                    direct_url, ap_title, ap_hash = self._resolve_aparat_direct_url(url, height_limit)
                    if not direct_url:
                        raise
                    safe_title = re.sub(r'[\\/*?:"<>|]', "_", ap_title).strip()
                    options["outtmpl"] = os.path.join(out_dir, f"{safe_title} [{ap_hash}].%(ext)s")
                    with yt_dlp.YoutubeDL(options) as ydl:
                        info = ydl.extract_info(direct_url, download=True)
                        expected_file = ydl.prepare_filename(info)
                else:
                    raise

            base_name = os.path.splitext(expected_file)[0]
            self._log(f"فایل ذخیره شد: {os.path.basename(expected_file)}")

            # مرحله ۲: دانلود زیرنویس فارسی
            if sub_enabled and not is_aparat and not self.cancel_event.is_set():
                self._log("مرحله ۲: بررسی زیرنویس فارسی...")
                sub_opts = dict(options)
                sub_opts.update({
                    "skip_download": True,
                    "writesubtitles": True,
                    "writeautomaticsub": True,
                    "subtitleslangs": ["fa"],
                    "subtitlesformat": "srt/vtt/best",
                    "sleep_subtitles": 2,
                })
                try:
                    with yt_dlp.YoutubeDL(sub_opts) as ydl_sub:
                        ydl_sub.download([url])

                    vtt_path = base_name + ".fa.vtt"
                    srt_path = base_name + ".fa.srt"
                    if os.path.exists(vtt_path) and not os.path.exists(srt_path):
                        self._convert_vtt_to_srt(vtt_path, srt_path)
                        self._log("زیرنویس فارسی به SRT تبدیل و ذخیره شد.")
                except Exception as sub_e:
                    self._log(f"زیرنویس دریافت نشد (محدودیت 429 یا عدم وجود): {sub_e}")

            self._set_status("عملیات دانلود با موفقیت به پایان رسید!", 1.0)

        except Exception as exc:
            self._set_status("خطا یا توقف در دانلود", 0)
            self._log(f"خطا: {exc}")
        finally:
            self._set_busy(False)

    @staticmethod
    def _convert_vtt_to_srt(vtt_path, srt_path):
        try:
            with open(vtt_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            srt_lines = []
            counter = 1
            for line in lines:
                stripped = line.strip()
                if stripped.startswith(("WEBVTT", "Kind:", "Language:")):
                    continue
                if "-->" in line:
                    parts = line.replace(".", ",").split("-->")
                    if len(parts) == 2:
                        start = parts[0].strip()
                        end = parts[1].strip().split(" ")[0]
                        srt_lines.append(f"{counter}\n{start} --> {end}\n")
                        counter += 1
                else:
                    srt_lines.append(line)
            with open(srt_path, "w", encoding="utf-8") as f:
                f.writelines(srt_lines)
            os.remove(vtt_path)
        except Exception:
            pass


def main(page: ft.Page):
    MobileDownloader(page)


if __name__ == "__main__":
    ft.app(target=main)
