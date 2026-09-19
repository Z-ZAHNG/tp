# -*- coding: utf-8 -*-
"""
eszytp 投票网站后端
- 网站页面在 wy 文件夹（本文件同级）
- 上传的图片与称号数据存放在 ../uploads 文件夹（图片文件 + candidates.json 一一对应）
运行：python app.py   然后浏览器打开 http://127.0.0.1:5000
"""
import io
import json
import time
import uuid
import threading
from datetime import datetime
from pathlib import Path

from flask import (Flask, request, jsonify, session,
                   send_from_directory, send_file)
from PIL import Image

# ---------- 路径与配置 ----------
BASE = Path(__file__).resolve().parent          # .../eszytp/wy
UPLOAD_DIR = BASE.parent / "uploads"            # .../eszytp/uploads  第二个子文件夹
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

CAND_FILE = UPLOAD_DIR / "candidates.json"      # 称号与图片对应关系 + 票数
MSG_FILE = UPLOAD_DIR / "messages.json"         # 广场留言

ADMIN_PASSWORD = "zgznb666"   # 管理员密码，可在此修改
SECRET_KEY = "eszytp-vote-secret-2026-please-change"
IMG_SIZE = 600                # 头像统一裁剪为 600x600（1:1）

app = Flask(__name__, static_folder=None)
app.secret_key = SECRET_KEY
lock = threading.Lock()


# ---------- 数据读写 ----------
def _load(path, default):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_candidates():
    return _load(CAND_FILE, [])


def save_candidates(data):
    _save(CAND_FILE, data)


def load_messages():
    return _load(MSG_FILE, [])


def save_messages(data):
    _save(MSG_FILE, data)


def next_id(items):
    return (max((it.get("id", 0) for it in items), default=0) + 1)


# ---------- 首次运行：生成示例候选人（可在管理员页删除） ----------
def make_placeholder(text, color, path):
    img = Image.new("RGB", (IMG_SIZE, IMG_SIZE), color)
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    # 简单画一个圆 + 文字
    draw.ellipse((140, 90, 460, 410), fill=(255, 255, 255))
    draw.text((IMG_SIZE // 2, 470), text, fill=(255, 255, 255), anchor="mm")
    img.save(path, "JPEG", quality=88)


def init_sample():
    if CAND_FILE.exists():
        return
    samples = [
        ("闪电侠", (231, 76, 60)),
        ("智多星", (52, 152, 219)),
        ("铁人", (39, 174, 96)),
        ("开心果", (243, 156, 18)),
    ]
    data = []
    for i, (title, color) in enumerate(samples, start=1):
        fname = f"c{i}_sample.jpg"
        make_placeholder(title, color, UPLOAD_DIR / fname)
        data.append({
            "id": i, "title": title, "image": fname,
            "votes": 0, "created": int(time.time())
        })
    save_candidates(data)


init_sample()


# ---------- 页面 ----------
@app.route("/")
def index():
    return send_file(BASE / "index.html")


@app.route("/admin")
def admin_page():
    return send_file(BASE / "admin.html")


@app.route("/uploads/<path:fname>")
def uploaded(fname):
    return send_from_directory(UPLOAD_DIR, fname)


# ---------- 公开接口 ----------
@app.route("/api/state")
def api_state():
    """投票页 / 广场页一次性获取全部公开数据"""
    cands = sorted(load_candidates(), key=lambda c: (-c["votes"], c["id"]))
    msgs = sorted(load_messages(), key=lambda m: -m["id"])
    return jsonify({"candidates": cands, "messages": msgs})


@app.route("/api/vote", methods=["POST"])
def api_vote():
    cid = (request.get_json(silent=True) or {}).get("id")
    with lock:
        data = load_candidates()
        for c in data:
            if c["id"] == cid:
                c["votes"] = int(c.get("votes", 0)) + 1
                save_candidates(data)
                return jsonify({"ok": True, "votes": c["votes"]})
    return jsonify({"ok": False, "msg": "候选人不存在"}), 404


@app.route("/api/message", methods=["POST"])
def api_message():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "匿名同学").strip()[:20]
    content = (body.get("content") or "").strip()[:300]
    if not content:
        return jsonify({"ok": False, "msg": "留言内容不能为空"}), 400
    with lock:
        msgs = load_messages()
        item = {
            "id": next_id(msgs),
            "name": name,
            "content": content,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        msgs.append(item)
        save_messages(msgs)
    return jsonify({"ok": True, "message": item})


@app.route("/api/signup", methods=["POST"])
def api_signup():
    """报名：上传称号(外号) + 一张图片，图片中心裁剪为 1:1"""
    title = (request.form.get("title") or "").strip()[:20]
    file = request.files.get("image")
    if not title:
        return jsonify({"ok": False, "msg": "请填写称号（外号）"}), 400
    if not file or not file.filename:
        return jsonify({"ok": False, "msg": "请选择一张照片"}), 400

    raw = file.read()
    try:
        img = Image.open(io.BytesIO(raw))
        img = img.convert("RGB")
        w, h = img.size
        s = min(w, h)
        left, top = (w - s) // 2, (h - s) // 2
        img = img.crop((left, top, left + s, top + s))
        img = img.resize((IMG_SIZE, IMG_SIZE), Image.LANCZOS)
    except Exception:
        return jsonify({"ok": False, "msg": "图片无法识别，请换一张"}), 400

    with lock:
        data = load_candidates()
        cid = next_id(data)
        safe = "".join(ch for ch in title if ch.isalnum() or '\u4e00' <= ch <= '\u9fff') or "candidate"
        fname = f"c{cid}_{safe}_{uuid.uuid4().hex[:6]}.jpg"
        img.save(UPLOAD_DIR / fname, "JPEG", quality=88)
        item = {
            "id": cid, "title": title, "image": fname,
            "votes": 0, "created": int(time.time())
        }
        data.append(item)
        save_candidates(data)
    return jsonify({"ok": True, "candidate": item})


# ---------- 管理员接口 ----------
def require_admin():
    return session.get("is_admin") is True


@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    pwd = (request.get_json(silent=True) or {}).get("password", "")
    if pwd == ADMIN_PASSWORD:
        session["is_admin"] = True
        return jsonify({"ok": True})
    return jsonify({"ok": False, "msg": "密码错误"}), 401


@app.route("/api/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("is_admin", None)
    return jsonify({"ok": True})


@app.route("/api/admin/candidate/update", methods=["POST"])
def admin_update():
    if not require_admin():
        return jsonify({"ok": False, "msg": "未登录"}), 401
    body = request.get_json(silent=True) or {}
    cid = body.get("id")
    with lock:
        data = load_candidates()
        for c in data:
            if c["id"] == cid:
                if body.get("title") is not None:
                    t = str(body["title"]).strip()[:20]
                    if t:
                        c["title"] = t
                if body.get("votes") is not None:
                    try:
                        c["votes"] = max(0, int(body["votes"]))
                    except Exception:
                        pass
                save_candidates(data)
                return jsonify({"ok": True, "candidate": c})
    return jsonify({"ok": False, "msg": "候选人不存在"}), 404


@app.route("/api/admin/candidate/delete", methods=["POST"])
def admin_delete_candidate():
    if not require_admin():
        return jsonify({"ok": False, "msg": "未登录"}), 401
    cid = (request.get_json(silent=True) or {}).get("id")
    with lock:
        data = load_candidates()
        target = next((c for c in data if c["id"] == cid), None)
        if not target:
            return jsonify({"ok": False, "msg": "候选人不存在"}), 404
        # 删除对应图片（示例/上传图）
        img_name = target.get("image", "")
        if img_name:
            p = UPLOAD_DIR / img_name
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass
        data = [c for c in data if c["id"] != cid]
        save_candidates(data)
    return jsonify({"ok": True})


@app.route("/api/admin/message/delete", methods=["POST"])
def admin_delete_message():
    if not require_admin():
        return jsonify({"ok": False, "msg": "未登录"}), 401
    mid = (request.get_json(silent=True) or {}).get("id")
    with lock:
        msgs = load_messages()
        new = [m for m in msgs if m["id"] != mid]
        if len(new) == len(msgs):
            return jsonify({"ok": False, "msg": "留言不存在"}), 404
        save_messages(new)
    return jsonify({"ok": True})


@app.route("/api/admin/votes/reset", methods=["POST"])
def admin_reset_votes():
    """重置票数：传 id 重置单人，不传则全部清零"""
    if not require_admin():
        return jsonify({"ok": False, "msg": "未登录"}), 401
    cid = (request.get_json(silent=True) or {}).get("id")
    with lock:
        data = load_candidates()
        for c in data:
            if cid is None or c["id"] == cid:
                c["votes"] = 0
        save_candidates(data)
    return jsonify({"ok": True})


if __name__ == "__main__":
    print("=" * 50)
    print("投票网站已启动")
    print("本机访问： http://127.0.0.1:5000")
    print("管理员页： http://127.0.0.1:5000/admin")
    print("上传图片/数据目录：", UPLOAD_DIR)
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False)
