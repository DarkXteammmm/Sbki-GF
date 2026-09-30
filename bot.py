import os
import re
import asyncio
import subprocess
import urllib.request

from pyrogram import Client, filters

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

app = Client(
    "linkbot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)

stop_flags = {}   # chat_id -> True agar /stop dabaya
procs = {}        # chat_id -> chalta hua ffmpeg process


def clean_name(s):
    s = re.sub(r'[\\/:*?"<>|\r\n]+', " ", s).strip()
    return s[:100] or "file"


def parse_links(path):
    """Har line: 'Title:URL' ya sirf 'URL'. Return: [(title, url), ...]"""
    items = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = re.search(r'https?://[^\s"\'<>]+', line)
            if not m:
                continue
            url = m.group(0)
            title = line[: m.start()].strip().rstrip(":").strip()
            if not title:
                title = os.path.basename(url.split("?")[0]) or "file"
            items.append((title, url))
    return items


def download_file(url, out):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(out, "wb") as f:
        while True:
            chunk = r.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)


def download_video(url, out, chat_id):
    p = subprocess.Popen(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", url,
            "-c", "copy", "-bsf:a", "aac_adtstoasc", out,
        ]
    )
    procs[chat_id] = p
    rc = p.wait()
    procs.pop(chat_id, None)
    if rc != 0:
        raise RuntimeError(f"ffmpeg exit code {rc}")


@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply(
        "Upload txt file\n\n"
        "Format (har line mein):\n"
        "Title:https://link\n\n"
        "Rokne ke liye /stop"
    )


@app.on_message(filters.command("stop"))
async def stop(client, message):
    chat_id = message.chat.id
    stop_flags[chat_id] = True
    p = procs.get(chat_id)
    if p:
        p.terminate()
    await message.reply("Stop kar diya. Chalti hui file ke baad extraction band ho jayega.")


@app.on_message(filters.document)
async def handle(client, message):
    chat_id = message.chat.id
    name = message.document.file_name or ""
    if not name.lower().endswith(".txt"):
        return await message.reply("Sirf .txt file bhejo")

    stop_flags[chat_id] = False
    path = await message.download()
    items = parse_links(path)
    os.remove(path)
    await message.reply(f"{len(items)} links mile. Rokne ke liye /stop")

    done = 0
    for idx, (title, url) in enumerate(items, start=1):
        if stop_flags.get(chat_id):
            await message.reply(f"Stopped. {done}/{len(items)} file ho chuki.")
            return

        low = url.lower()
        caption = f"Index: {idx}\nTitle: {title}"
        fname = clean_name(title)
        out = f"dl_{message.id}_{idx}"

        try:
            if ".pdf" in low:
                out += ".pdf"
                await asyncio.to_thread(download_file, url, out)
                if fname.lower().endswith(".pdf"):
                    fname = fname[:-4]
                await message.reply_document(
                    out, file_name=fname + ".pdf", caption=caption
                )
            elif ".m3u8" in low:
                out += ".mp4"
                await asyncio.to_thread(download_video, url, out, chat_id)
                await message.reply_video(
                    out, file_name=fname + ".mp4", caption=caption,
                    supports_streaming=True,
                )
            else:
                continue
            done += 1
        except Exception as e:
            if stop_flags.get(chat_id):
                await message.reply(f"Stopped. {done}/{len(items)} file ho chuki.")
                return
            await message.reply(f"Fail (Index {idx}): {title}\n{e}")
        finally:
            if os.path.exists(out):
                os.remove(out)

    await message.reply(f"Done. {done}/{len(items)} files bheji.")


app.run()
