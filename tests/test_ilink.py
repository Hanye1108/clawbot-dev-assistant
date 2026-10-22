from devbot.ilink import split_text


def test_split_short():
    assert split_text("abc", 10) == ["abc"]


def test_split_on_blank_lines():
    blocks = [f"{i}. " + "x" * 300 for i in range(1, 8)]
    parts = split_text("\n\n".join(blocks), 1000)
    assert all(len(p) <= 1000 for p in parts)
    assert "\n\n".join(parts) == "\n\n".join(blocks)     # 没丢内容，也没把项目拆开
    assert all(p.startswith(tuple(f"{i}." for i in range(1, 8))) for p in parts)


def test_split_long_block():
    text = "\n".join("y" * 90 for _ in range(30))
    parts = split_text(text, 1000)
    assert all(len(p) <= 1000 for p in parts) and len(parts) >= 3
