import os
import re
import glob
import asyncio
import subprocess
import urllib.request

from pyrogram import Client, filters
from yt_dlp import YoutubeDL

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

MAX_SIZE = 2000 * 1024 * 1024  # Telegram limit ~2GB

app = Client(
    "linkbot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)

stop_flags = {}   # chat_id -> True agar /stop dabaya
procs = {}        # chat_id -> chalta hua ffmpeg process


def clean_name(s):
    s = re.sub(r'[\\/:*?"<>|\r\n]+', " ", s or "").strip()
    return s[:100] or "file"


def parse_text(text):
    """Har line: 'Title:URL' ya sirf 'URL'. Return: [(title|None, url)]"""
    items = []
    for line in text.splitlines():
        m = re.search(r'https?://[^\s"\'<>]+', line)
        if not m:
            continue
        title = line[: m.start()].strip().rstrip(":").strip()
        items.append((title or None, m.group(0)))
    return items


def download_file(url, out):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(out, "wb") as f:
        while True:
            chunk = r.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)


def expand(url):
    """Playlist ho toh uski sab videos, warna [(title, url)]"""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
    }
    try:
        with YoutubeDL(opts) as y:
            info = y.extract_info(url, download=False)
    except Exception:
        return [(None, url)]
    if info and info.get("entries"):
        out = []
        for e in info["entries"]:
            if not e:
                continue
            u = e.get("url") or e.get("webpage_url")
            if u:
                out.append((e.get("title"), u))
        return out or [(None, url)]
    return [((info or {}).get("title"), url)]


def download_media(url, base, chat_id):
    def hook(d):
        if stop_flags.get(chat_id):
            raise Exception("stopped")

    opts = {
        "outtmpl": base + ".%(ext)s",
        "format": "bv*[height<=720]+ba/b[height<=720]/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 5,
        "fragment_retries": 10,
        "concurrent_fragment_downloads": 4,
        "progress_hooks": [hook],
    }
    with YoutubeDL(opts) as y:
        y.download([url])
    files = [f for f in glob.glob(base + ".*")
             if not f.endswith((".part", ".ytdl"))]
    if not files:
        raise RuntimeError("file nahi bani")
    return max(files, key=os.path.getsize)


def download_ffmpeg(url, base, chat_id):
    out = base + ".mp4"
    p = subprocess.Popen([
        "ffmpeg", "-y", "-loglevel", "error",
        "-user_agent", "Mozilla/5.0", "-i", url,
        "-c", "copy", out,
    ])
    procs[chat_id] = p
    rc = p.wait()
    procs.pop(chat_id, None)
    if rc != 0:
        raise RuntimeError(f"ffmpeg exit code {rc}")
    return out


def download_direct(url, base, chat_id):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        ctype = r.headers.get("Content-Type", "")
        if not (ctype.startswith("video/") or "octet-stream" in ctype):
            raise RuntimeError(f"video nahi hai ({ctype or 'unknown'})")
        ext = os.path.splitext(url.split("?")[0])[1].lower()
        if ext not in (".mp4", ".mkv", ".webm", ".mov", ".avi", ".ts"):
            ext = ".mp4"
        out = base + ext
        with open(out, "wb") as f:
            while True:
                if stop_flags.get(chat_id):
                    raise Exception("stopped")
                chunk = r.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
    return out


def cleanup(base):
    for f in glob.glob(base + ".*"):
        try:
            os.remove(f)
        except OSError:
            pass


async def run_job(message, items):
    chat_id = message.chat.id
    stop_flags[chat_id] = False
    await message.reply(f"{len(items)} links mile. Rokne ke liye /stop")

    n = 0
    done = 0
    for title, url in items:
        if stop_flags.get(chat_id):
            break

        is_pdf = ".pdf" in url.lower()
        if is_pdf:
            entries = [(title, url)]
        else:
            entries = await asyncio.to_thread(expand, url)
            if len(entries) == 1 and title:
                entries = [(title, entries[0][1])]
            elif len(entries) > 1:
                await message.reply(f"Playlist: {len(entries)} videos mili")

        for etitle, eurl in entries:
            if stop_flags.get(chat_id):
                break
            n += 1
            name = etitle or "file"
            caption = f"Index: {n}\nTitle: {name}"
            base = f"dl_{message.id}_{n}"
            try:
                if is_pdf:
                    path = base + ".pdf"
                    await asyncio.to_thread(download_file, eurl, path)
                    fname = clean_name(name)
                    if fname.lower().endswith(".pdf"):
                        fname = fname[:-4]
                    await message.reply_document(
                        path, file_name=fname + ".pdf", caption=caption
                    )
                else:
                    await message.reply(f"Download: {n}. {name}")
                    path = None
                    errors = []
                    for fn in (download_media, download_ffmpeg, download_direct):
                        if stop_flags.get(chat_id):
                            break
                        try:
                            path = await asyncio.to_thread(
                                fn, eurl, base, chat_id
                            )
                            break
                        except Exception as e:
                            errors.append(f"{fn.__name__}: {str(e)[:120]}")
                            print(fn.__name__, eurl, e, flush=True)
                            cleanup(base)
                    if not path:
                        if stop_flags.get(chat_id):
                            raise Exception("stopped")
                        raise RuntimeError("\n".join(errors))
                    if os.path.getsize(path) > MAX_SIZE:
                        raise RuntimeError("file 2GB se badi hai")
                    ext = os.path.splitext(path)[1]
                    await message.reply_video(
                        path,
                        file_name=clean_name(name) + ext,
                        caption=caption,
                        supports_streaming=True,
                    )
                done += 1
            except Exception as e:
                if stop_flags.get(chat_id):
                    break
                await message.reply(f"Fail ({n}) {name}\n{str(e)[:300]}")
            finally:
                cleanup(base)

    if stop_flags.get(chat_id):
        await message.reply(f"Stopped. {done} file ho chuki.")
    else:
        await message.reply(f"Done. {done}/{n} files bheji.")


@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply(
        "Upload txt file ya seedha link bhejo\n\n"
        "Format (har line mein):\n"
        "Title:https://link\n\n"
        "YouTube, playlist, m3u8 aur PDF links chalte hain.\n"
        "Rokne ke liye /stop"
    )


@app.on_message(filters.command("stop"))
async def stop(client, message):
    chat_id = message.chat.id
    stop_flags[chat_id] = True
    p = procs.get(chat_id)
    if p:
        p.terminate()
    await message.reply("Stop kar raha hoon...")


@app.on_message(filters.document)
async def on_file(client, message):
    name = message.document.file_name or ""
    if not name.lower().endswith(".txt"):
        return await message.reply("Sirf .txt file bhejo")
    path = await message.download()
    with open(path, encoding="utf-8", errors="ignore") as f:
        items = parse_text(f.read())
    os.remove(path)
    if not items:
        return await message.reply("File mein koi link nahi mila")
    await run_job(message, items)


@app.on_message(filters.text & ~filters.command(["start", "stop"]))
async def on_text(client, message):
    items = parse_text(message.text)
    if items:
        await run_job(message, items)


app.run()
