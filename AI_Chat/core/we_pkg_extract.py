"""
Wallpaper Engine .pkg / .tex 解析与素材提取（纯 Python 实现）

- .pkg: PKGV0018 容器，条目表 [name_len][name][offset][size]（数据区统一排布）
- .tex: TEXV0005 + TEXI0001 头，图像容器 TEXB0001-0004
  * TEXB0003/0004: mipmap 直接是 PNG/JPG/GIF/MP4 等标准文件字节
  * TEXB0001/0002: 原始像素（RGBA8888/R8/RG88）或 DXT1/3/5 块压缩（用 DDS 头包装交给 Pillow 解码）
格式规格参考开源项目 repkg (github.com/notscuffed/repkg) 的逆向结果。
"""
import io
import os
import struct

try:
    from PIL import Image
    _HAS_PIL = True
except ImportError:  # pragma: no cover
    _HAS_PIL = False

try:
    from lz4 import block as _lz4_block

    def _lz4_decompress(data: bytes, uncompressed_size: int) -> bytes:
        return _lz4_block.decompress(data, uncompressed_size=uncompressed_size)
except ImportError:  # pragma: no cover
    _lz4_decompress = None

# FreeImageFormat（repkg 定义，PNG=13 JPEG=2 GIF=25 MP4=35）
FIF_UNKNOWN, FIF_JPEG, FIF_PNG, FIF_GIF, FIF_MP4 = -1, 2, 13, 25, 35
_FIF_EXT = {
    0: ".bmp", 1: ".ico", 2: ".jpg", 3: ".jng", 7: ".pbm", 10: ".pcx",
    11: ".pgm", 13: ".png", 14: ".ppm", 16: ".ras", 17: ".tga", 18: ".tif",
    20: ".psd", 23: ".xpm", 25: ".gif", 28: ".sgi", 29: ".exr",
}

# TexFormat
TEX_RGBA8888, TEX_DXT5, TEX_DXT3, TEX_DXT1, TEX_RG88, TEX_R8 = 0, 4, 6, 7, 8, 9

_TEX_MAGIC = b"TEXV0005TEXI0001"
MAX_MIPMAP_COUNT = 32
MAX_BYTES = 512 * 1024 * 1024


def parse_pkg_entries(data: bytes):
    """解析 pkg 条目表，返回 [(name, offset, size)]
    条目表里的 offset 是相对数据区起点（条目表结束处）的偏移"""
    pos = 0
    (vlen,) = struct.unpack_from("<I", data, pos)
    pos += 4 + vlen          # 版本串 "PKGV0018"
    pos += 4                 # 未知 u32（条目计数/标志）
    entries = []
    total = len(data)
    while pos + 12 <= total:
        (nlen,) = struct.unpack_from("<I", data, pos)
        pos += 4
        if nlen == 0 or nlen > 1024:
            pos -= 4         # 已进入数据区，回退这 4 字节
            break
        name = data[pos:pos + nlen].decode("utf-8", "replace")
        pos += nlen
        rel_off, size = struct.unpack_from("<II", data, pos)
        pos += 8
        entries.append((name, rel_off, size))
    data_base = pos          # 数据区起点 = 条目表结束处
    return [(n, data_base + o, s) for (n, o, s) in entries]


def _read_nstring(data, pos):
    (n,) = struct.unpack_from("<I", data, pos)
    pos += 4
    return data[pos:pos + n].decode("utf-8", "replace"), pos + n


def _decode_dds_block(width, height, fourcc: bytes, payload: bytes) -> bytes:
    """把 DXT 压缩像素包装成 DDS 文件交给 Pillow 解码，返回 RGBA 字节"""
    DDSD_CAPS, DDSD_HEIGHT, DDSD_WIDTH = 0x1, 0x2, 0x4
    DDSD_PIXELFORMAT, DDSD_LINEARSIZE = 0x1000, 0x80000
    DDPF_FOURCC, DDSCAPS_TEXTURE = 0x4, 0x1000
    linear = ((width + 3) // 4) * ((height + 3) // 4) * (8 if fourcc == b"DXT1" else 16)
    header = (
        struct.pack("<7I", 124,
                    DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT | DDSD_LINEARSIZE,
                    height, width, linear, 0, 0)
        + b"\x00" * 44                                   # reserved1[11]
        + struct.pack("<3I", 32, DDPF_FOURCC,            # DDS_PIXELFORMAT: size, flags
                      struct.unpack("<I", fourcc)[0])    # fourcc
        + b"\x00" * 20                                   # RGBBitCount + 4 masks
        + struct.pack("<4I", DDSCAPS_TEXTURE, 0, 0, 0)   # caps, caps2-4
        + b"\x00" * 4
    )
    assert len(header) == 124
    dds = b"DDS " + header + payload
    with Image.open(io.BytesIO(dds)) as im:
        im.load()
        return im.convert("RGBA").tobytes()


def _read_cstr(buf, pos, maxlen=16):
    """读 NUL 结尾的 ASCII 串（WE magic 格式，如 b'TEXV0005\\0'）"""
    end = buf.find(b"\x00", pos, pos + maxlen)
    if end < 0:
        end = pos + maxlen
        return buf[pos:end].decode("ascii", "replace"), end
    return buf[pos:end].decode("ascii", "replace"), end + 1


def _sniff_file(payload: bytes):
    """按文件头嗅探嵌入的标准文件，返回 (ext, payload) 或 None"""
    if len(payload) < 12:
        return None
    if payload[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png", payload
    if payload[:3] == b"\xff\xd8\xff":
        return ".jpg", payload
    if payload[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif", payload
    if payload[4:8] == b"ftyp":
        return ".mp4", payload
    return None


def decode_tex(tex: bytes):
    """解码 .tex，返回 (kind, width, height, payload)
    kind: 'image' → payload 为 PIL Image；'file' → payload 为 (ext, 原始文件字节)"""
    if not _HAS_PIL:
        raise RuntimeError("需要 Pillow 库")
    magic1, pos = _read_cstr(tex, 0)
    if magic1 != "TEXV0005":
        raise ValueError(f"不是 WE tex 文件 (magic={magic1})")
    magic2, pos = _read_cstr(tex, pos)
    if magic2 != "TEXI0001":
        raise ValueError(f"不是 WE tex 文件 (magic2={magic2})")
    tex_format, flags, tex_w, tex_h, img_w, img_h, _unk = struct.unpack_from("<7i", tex, pos)
    pos += 28

    magic, pos = _read_cstr(tex, pos)
    if not magic.startswith("TEXB"):
        raise ValueError(f"未知图像容器 {magic}")
    version = int(magic[4:])

    # 顺序：图像数 → [FreeImageFormat → [isVideoMp4]] → 逐图像读 mipmap
    (image_count,) = struct.unpack_from("<i", tex, pos)
    pos += 4
    fif = FIF_UNKNOWN
    if magic in ("TEXB0003", "TEXB0004"):
        (fif,) = struct.unpack_from("<i", tex, pos)
        pos += 4
    if magic == "TEXB0004":
        (is_mp4,) = struct.unpack_from("<i", tex, pos)
        pos += 4
        if fif == FIF_UNKNOWN and is_mp4 == 1:
            fif = FIF_MP4
    if version == 4 and fif != FIF_MP4:
        version = 3
    image_count = min(max(image_count, 1), 8)

    m = None
    for _ in range(image_count):
        (mipmap_count,) = struct.unpack_from("<i", tex, pos)
        pos += 4
        mipmap_count = min(max(mipmap_count, 1), MAX_MIPMAP_COUNT)
        for j in range(mipmap_count):
            if version == 1:
                w, h = struct.unpack_from("<2i", tex, pos)
                pos += 8
                lz4_flag, decomp_size = 0, 0
            elif version == 4:
                p1, p2 = struct.unpack_from("<2i", tex, pos)
                pos += 8
                _cond, pos = _read_nstring(tex, pos)
                p3, = struct.unpack_from("<i", tex, pos)
                pos += 4
                w, h = struct.unpack_from("<2i", tex, pos)
                pos += 8
                lz4_flag, decomp_size = struct.unpack_from("<2i", tex, pos)
                pos += 8
            else:
                w, h = struct.unpack_from("<2i", tex, pos)
                pos += 8
                lz4_flag, decomp_size = struct.unpack_from("<2i", tex, pos)
                pos += 8
            (blen,) = struct.unpack_from("<i", tex, pos)
            pos += 4
            payload = tex[pos:pos + blen]
            pos += blen
            if j == 0 and m is None:
                if lz4_flag == 1:
                    if _lz4_decompress is None:
                        raise RuntimeError("该 tex 使用 LZ4 压缩，需要 pip install lz4")
                    payload = _lz4_decompress(payload, decomp_size)
                m = (w, h, payload)

    if m is None:
        raise ValueError("tex 中没有 mipmap")
    w, h, payload = m

    # 标准图像/视频文件（按 FreeImageFormat 或文件头嗅探）
    sniffed = _sniff_file(payload) if fif == FIF_UNKNOWN else None
    if fif == FIF_MP4 or (flags & 32) or sniffed:
        hit = sniffed or (".mp4", payload)
        return "file", w, h, hit
    if fif != FIF_UNKNOWN:
        ext = _FIF_EXT.get(fif)
        if ext:
            return "file", w, h, (ext, payload)

    if tex_format == TEX_RGBA8888:
        im = Image.frombytes("RGBA", (w, h), payload)
    elif tex_format == TEX_R8:
        im = Image.frombytes("L", (w, h), payload)
    elif tex_format == TEX_RG88:
        im = Image.frombytes("LA", (w, h), payload)
    elif tex_format in (TEX_DXT1, TEX_DXT3, TEX_DXT5):
        fourcc = {TEX_DXT1: b"DXT1", TEX_DXT3: b"DXT3", TEX_DXT5: b"DXT5"}[tex_format]
        rgba = _decode_dds_block(w, h, fourcc, payload)
        im = Image.frombytes("RGBA", (w, h), rgba)
    else:
        raise ValueError(f"不支持的像素格式 {tex_format}")
    return "image", img_w or w, img_h or h, im


def extract_media(pkg_path: str, out_dir: str, min_size: int = 256, progress=None):
    """从 scene.pkg 提取所有可用的图像/视频素材到 out_dir，返回保存的文件列表"""
    with open(pkg_path, "rb") as f:
        data = f.read()
    entries = parse_pkg_entries(data)
    os.makedirs(out_dir, exist_ok=True)
    saved = []
    for i, (name, offset, size) in enumerate(entries):
        if progress:
            progress(i + 1, len(entries), name)
        if not name.lower().endswith(".tex"):
            continue
        try:
            kind, w, h, payload = decode_tex(data[offset:offset + size])
        except Exception:
            continue
        if max(w, h) < min_size:  # 跳过小图标/噪声贴图
            continue
        if kind == "file":
            ext, blob = payload
            out = os.path.join(out_dir, f"{i:02d}_{os.path.basename(name)[:40]}{ext}")
            with open(out, "wb") as fo:
                fo.write(blob)
        else:
            im = payload
            if im.width > w or im.height > h:
                im = im.crop((0, 0, w, h))
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGB")
            out = os.path.join(out_dir, f"{i:02d}_{os.path.basename(name)[:40]}.png")
            im.save(out)
        saved.append(out)
    return saved
