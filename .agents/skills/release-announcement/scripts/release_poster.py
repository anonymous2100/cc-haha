#!/usr/bin/env python3
"""Find a release note and render an editorial, text-accurate WeChat poster."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import deque
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


VERSION_RE = re.compile(r"^release-notes/v(\d+)\.(\d+)\.(\d+)\.md$")
LOGIN_RE = re.compile(r"(?<![A-Za-z0-9._%+-])@([A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)")
RELEASE_HEADING_RE = re.compile(r"(?m)^#\s+opencode-haha v\d+\.\d+\.\d+\s*$")
CLOSING_PUNCTUATION = set("，。、；：！？）》」』】〕”’％")
OPENING_PUNCTUATION = set("（《「『【〔“‘")
POSTER_WIDTH = 1080
MAX_POSTER_HEIGHT = 16000
MARGIN, RIGHT = 64, 1016
CONTENT_WIDTH = RIGHT - MARGIN
# Swiss layout: one signal-orange hero, a paper body, an ink closing band.
PALETTE = {
    "signal": "#FF5B23",
    "paper": "#F1F0EB",
    "panel": "#E3E1D9",
    "ink": "#151515",
    "body": "#3B3B38",
    "accent_ink": "#A8340B",
    "night_text": "#F1F0EB",
    "night_body": "#CFCCC4",
    "night_rule": "#3A3A38",
}
# (path, collection index). Hiragino Sans GB: 0 = W3, 2 = W6; Noto CJK: 2 = SC.
FONT_CANDIDATES = {
    "regular": [
        ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
        ("/System/Library/Fonts/STHeiti Light.ttc", 1),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),
        ("C:/Windows/Fonts/msyh.ttc", 0),
    ],
    "bold": [
        ("/System/Library/Fonts/Hiragino Sans GB.ttc", 2),
        ("/System/Library/Fonts/STHeiti Medium.ttc", 1),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 2),
        ("C:/Windows/Fonts/msyhbd.ttc", 0),
    ],
    "heavy": [
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc", 2),
        ("/System/Library/Fonts/Hiragino Sans GB.ttc", 2),
        ("/System/Library/Fonts/STHeiti Medium.ttc", 1),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 2),
        ("C:/Windows/Fonts/msyhbd.ttc", 0),
    ],
    # Latin-only numerals: version, item numbers.
    "display": [
        ("/System/Library/Fonts/HelveticaNeue.ttc", 9),
        ("/System/Library/Fonts/Avenir Next Condensed.ttc", 8),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf", 0),
        ("C:/Windows/Fonts/arialbd.ttf", 0),
    ],
}


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def release_candidates(repo):
    notes = repo / "release-notes"
    candidates = []
    if notes.is_dir():
        for path in notes.glob("v*.md"):
            relative = path.relative_to(repo).as_posix()
            match = VERSION_RE.fullmatch(relative)
            if match:
                candidates.append((tuple(map(int, match.groups())), 4, "working-tree", relative))

    for rank, ref in ((3, "HEAD"), (2, "main"), (1, "origin/main")):
        result = git(repo, "ls-tree", "-r", "--name-only", ref, "--", "release-notes")
        if result.returncode:
            continue
        for relative in result.stdout.splitlines():
            match = VERSION_RE.fullmatch(relative)
            if match:
                candidates.append((tuple(map(int, match.groups())), rank, ref, relative))
    return candidates


def chinese_release_section(markdown):
    headings = list(RELEASE_HEADING_RE.finditer(markdown))
    if len(headings) >= 2:
        sections = [
            markdown[heading.start():(headings[index + 1].start() if index + 1 < len(headings) else len(markdown))]
            for index, heading in enumerate(headings)
        ]
    else:
        sections = [markdown]
    # Older releases put English first and Chinese in <details>; others invert
    # that order or repeat the H1 without <details>.
    candidates = []
    for section in sections:
        candidates.extend(re.split(r"(?i)<details(?:\s[^>]*)?>", section))
    selected = max(candidates, key=lambda part: len(re.findall(r"[\u4e00-\u9fff]", part)))
    if len(re.findall(r"[\u4e00-\u9fff]", selected)) < 10:
        raise ValueError("发布说明里未找到足够的中文正文，请人工核对语言版本")
    return re.sub(r"(?is)</?details[^>]*>|<summary[^>]*>.*?</summary>", "", selected).strip() + "\n"


def is_explicit_credit(line, login):
    escaped = re.escape(login)
    if re.search(rf"\*\*@{escaped}\*\*", line, re.IGNORECASE):
        return True
    return bool(re.search(rf"(?:感谢|致谢|代码贡献者|贡献者)[^\n@]{{0,70}}@{escaped}\b", line, re.IGNORECASE))


def wrap_lines(value, width, measure):
    result, current = [], ""
    # Latin model names and IDs stay together; CJK wraps character by character.
    tokens = re.findall(r"@?[A-Za-z0-9][A-Za-z0-9._/+:-]*|.", str(value), flags=re.DOTALL)
    # An unbroken URL/model name must never escape the image's safe area.
    pending = deque(part for token in tokens for part in (list(token) if token != "\n" and measure(token) > width else [token]))
    while pending:
        token = pending.popleft()
        if token == "\n":
            result.append(current)
            current = ""
            continue
        trial = current + token
        if current and measure(trial) > width:
            if token in CLOSING_PUNCTUATION:
                tail_match = re.search(r"(?:[A-Za-z0-9._/+:-]+|.)$", current)
                tail = tail_match.group(0) if tail_match else ""
                if measure(tail + token) > width:
                    tail = current[-1]
                prefix = current[:-len(tail)].rstrip() if tail else ""
                if prefix:
                    result.append(prefix)
                current = tail + token
                if measure(current) > width:
                    raise ValueError("排版宽度不足以容纳标点，请增加可用宽度")
            elif current[-1] in OPENING_PUNCTUATION:
                prefix = current[:-1].rstrip()
                if prefix:
                    result.append(prefix)
                current = current[-1]
                if measure(current + token) > width:
                    if len(token) == 1:
                        raise ValueError("排版宽度不足以容纳标点，请增加可用宽度")
                    pending.extendleft(reversed(list(token)))
                else:
                    current += token
            else:
                result.append(current.rstrip())
                current = token.lstrip()
        else:
            current = trial
    result.append(current)
    return result


def scan(repo, requested_version=None):
    candidates = release_candidates(repo)
    if requested_version:
        requested = requested_version.removeprefix("v")
        if not re.fullmatch(r"\d+\.\d+\.\d+", requested):
            raise ValueError(f"无效版本号：{requested_version}")
        target = tuple(map(int, requested.split(".")))
        candidates = [candidate for candidate in candidates if candidate[0] == target]
    if not candidates:
        label = requested_version or "最新版本"
        raise ValueError(f"未找到 {label} 的 release-notes Markdown")
    version, _, source, relative = max(candidates)
    if source == "working-tree":
        markdown = (repo / relative).read_text(encoding="utf-8")
    else:
        result = git(repo, "show", f"{source}:{relative}")
        if result.returncode:
            raise ValueError(f"无法从 {source} 读取 {relative}: {result.stderr.strip()}")
        markdown = result.stdout

    chinese = chinese_release_section(markdown)
    mentions = {}
    for line in chinese.splitlines():
        for match in LOGIN_RE.finditer(line):
            login = match.group(1)
            key = login.lower()
            entry = mentions.setdefault(key, {"login": login, "lines": [], "credit_candidate": False})
            if line not in entry["lines"]:
                entry["lines"].append(line.strip())
            if is_explicit_credit(line, login):
                entry["credit_candidate"] = True

    return {
        "version": ".".join(map(str, version)),
        "source": source,
        "path": relative,
        "sha256": hashlib.sha256(chinese.encode("utf-8")).hexdigest(),
        "chinese_markdown": chinese,
        "mentions": list(mentions.values()),
    }


def choose_font(role):
    for path, index in FONT_CANDIDATES[role]:
        if Path(path).is_file():
            return path, index
    if role == "display":
        return choose_font("bold")
    raise RuntimeError("缺少可用的中文系统字体；请提供冬青黑体、华文黑体、Noto Sans CJK 或微软雅黑")


def check_spec(spec, scan_data, allow_offline_avatars=False):
    if not isinstance(spec, dict):
        raise ValueError("poster spec 必须是 JSON 对象")
    if spec.get("version") != scan_data.get("version"):
        raise ValueError("poster spec 的 version 与最新 release note 不一致")
    for field in ("features", "fixes", "contributors"):
        if not isinstance(spec.get(field), list):
            raise ValueError(f"poster spec 缺少数组字段 {field}")
    if not spec["features"] and not spec["fixes"]:
        raise ValueError("至少需要一个主要功能或修复项")
    if len(spec["features"]) > 6 or len(spec["fixes"]) > 12:
        raise ValueError("内容过多：最多 6 项功能、12 项修复，请先提炼")
    mention_ids = {m["login"].lower() for m in scan_data.get("mentions", []) if m.get("credit_candidate") is True}
    seen = set()
    for person in spec["contributors"]:
        login = person.get("login", "")
        if not isinstance(login, str) or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", login):
            raise ValueError(f"无效 GitHub ID: {login!r}")
        if login.lower() not in mention_ids:
            raise ValueError(f"贡献者 @{login} 未在 release note 中文部分明确署名")
        if login.lower() in seen:
            raise ValueError(f"重复的贡献者 @{login}")
        seen.add(login.lower())
        if not person.get("contribution"):
            raise ValueError(f"缺少 @{login} 的贡献概述")
        if person.get("avatar_path") and not allow_offline_avatars:
            raise ValueError("avatar_path 仅供显式离线测试使用，正式成图必须核验 GitHub 头像")
    for field in ("features", "fixes"):
        for item in spec[field]:
            if not item.get("title") or not item.get("body"):
                raise ValueError(f"{field} 每项都需要 title 和 body")
    if not isinstance(spec.get("extras", []), list):
        raise ValueError("extras 必须是数组")
    for extra in spec.get("extras", []):
        if not all(extra.get(key) for key in ("title", "headline", "body")):
            raise ValueError("extras 每项需要 title、headline、body")


def get_avatar(person, spec_path, avatar_dir, allow_offline_avatars=False):
    from PIL import Image

    login = person["login"]
    if person.get("avatar_path"):
        if not allow_offline_avatars:
            raise ValueError("正式成图不能使用 avatar_path")
        path = Path(person["avatar_path"])
        if not path.is_absolute():
            path = spec_path.parent / path
        return Image.open(path).convert("RGB")

    request = Request(
        "https://api.github.com/users/" + quote(login),
        headers={"Accept": "application/vnd.github+json", "User-Agent": "cc-haha-release-announcement"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            profile = json.load(response)
        if profile.get("login", "").lower() != login.lower():
            raise ValueError(f"GitHub 返回的账号与 @{login} 不符")
        url = profile.get("avatar_url")
        if not url:
            raise ValueError(f"@{login} 没有公开头像地址")
        image_request = Request(url + "&s=256", headers={"User-Agent": "cc-haha-release-announcement"})
        with urlopen(image_request, timeout=20) as response:
            content = response.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"获取 @{login} 的 GitHub 头像失败：{exc}") from exc
    avatar_dir.mkdir(parents=True, exist_ok=True)
    path = avatar_dir / (login + ".png")
    path.write_bytes(content)
    return Image.open(path).convert("RGB")


def render(spec, scan_data, spec_path, output, allow_offline_avatars=False):
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    check_spec(spec, scan_data, allow_offline_avatars)
    p = PALETTE
    margin, right, content_width = MARGIN, RIGHT, CONTENT_WIDTH
    body_x, body_width = margin + 160, content_width - 160
    product = str(spec.get("product") or "Claude Code Haha")
    features, extras, fixes, people = spec["features"], spec.get("extras", []), spec["fixes"], spec["contributors"]
    faces, strokes, avatars = {}, {}, {}

    def face(size, role="regular"):
        key = (size, role)
        if key not in faces:
            path, index = choose_font(role)
            faces[key] = ImageFont.truetype(path, size, index=index)
            # Without a black weight, only display-size headings get a 1px
            # stroke; thicker strokes fill in dense characters such as 重.
            strokes[faces[key]] = 1 if role == "heavy" and size >= 60 and "Black" not in path else 0
        return faces[key]

    def avatar(person):
        if person["login"] not in avatars:
            photo = get_avatar(person, spec_path, output.parent / "avatars", allow_offline_avatars)
            avatars[person["login"]] = ImageOps.fit(photo, (96, 96), method=Image.Resampling.LANCZOS)
        return avatars[person["login"]]

    def layout(canvas, paint):
        """Lay out the whole poster; draw only when paint is true. Returns (height, bands)."""
        draw = ImageDraw.Draw(canvas)
        bands = []

    # Compact hero: the first release content appears in the first phone viewport.
    draw.rectangle((0, 0, W, 230), fill=ink)
    product = str(spec.get("product") or "opencode-haha").upper()
    write(64, 40, f"{product}  ·  v{spec['version']}", face(29, True), "#D6B99E", 950)
    draw.text((64, 99), "新版本发布", font=face(63, True), fill="#F4EFE4")
    draw.line((64, 207, 1016, 207), fill=rust, width=4)

        def lines(value, text_face, width):
            return wrap_lines(value, width, lambda text: measure(text, text_face))

        def put(x, y, text, text_face, color, anchor="lt"):
            if paint:
                width = strokes[text_face]
                x += width if anchor[0] == "l" else -width
                draw.text((x, y), text, font=text_face, fill=color, anchor=anchor, stroke_width=width, stroke_fill=color)

        def rect(box, **style):
            if paint:
                draw.rectangle(box, **style)

        def balanced(value, text_face, width):
            # A paragraph ending on a short tail (an orphaned character or two)
            # is rebalanced by narrowing the measure while the line count holds.
            best = lines(value, text_face, width)
            if len(best) < 2 or measure(best[-1], text_face) >= width / 3:
                return best
            low, high = int(width * 0.6), int(width)
            while low < high:
                middle = (low + high) // 2
                try:
                    trial = lines(value, text_face, middle)
                except ValueError:
                    trial = None
                if trial is not None and len(trial) <= len(best):
                    high = middle
                else:
                    low = middle + 1
            return lines(value, text_face, high)

        def write(x, y, value, text_face, color, width, leading=1.55, balance=False):
            for text_line in (balanced if balance else lines)(value, text_face, width):
                put(x, y, text_line, text_face, color)
                y += round(text_face.size * leading)
            return y

    draw.text((64, y), f"{spec.get('product') or 'opencode-haha'}  ·  v{spec['version']}", font=face(28, True), fill=ink)
    if spec.get("footer_url"):
        draw.text((64, y + 48), spec["footer_url"], font=face(27), fill=muted)
    y += 137
    if y > MAX_H:
        raise ValueError(f"海报高度 {y}px 超出上限，请减少内容")
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.crop((0, 0, POSTER_WIDTH, height)).save(output, optimize=True)
    return (POSTER_WIDTH, height)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    scan_cmd = commands.add_parser("scan", help="查找最新 release note，并输出中文内容与署名候选")
    scan_cmd.add_argument("--repo", type=Path, default=Path.cwd())
    scan_cmd.add_argument("--version", help="指定旧版本进行复测，例如 0.6.6；默认选最新版本")
    scan_cmd.add_argument("--out", type=Path, required=True)
    render_cmd = commands.add_parser("render", help="从经过审核的 JSON 绘制微信群长图")
    render_cmd.add_argument("--scan", type=Path, required=True)
    render_cmd.add_argument("--spec", type=Path, required=True)
    render_cmd.add_argument("--out", type=Path, required=True)
    render_cmd.add_argument("--allow-offline-avatars", action="store_true", help="仅测试用：允许 avatar_path 跳过 GitHub 请求")
    args = parser.parse_args()
    try:
        if args.command == "scan":
            data = scan(args.repo.resolve(), args.version)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            credited = sum(mention["credit_candidate"] for mention in data["mentions"])
            print(f"v{data['version']} | {data['source']}:{data['path']} | {credited} credits / {len(data['mentions'])} mentions | {args.out}")
        else:
            scan_data = json.loads(args.scan.read_text(encoding="utf-8"))
            spec = json.loads(args.spec.read_text(encoding="utf-8"))
            width, height = render(spec, scan_data, args.spec, args.out, args.allow_offline_avatars)
            print(f"{args.out} | {width}x{height}")
    except (ValueError, RuntimeError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
