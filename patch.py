#!/usr/bin/env python3

import os
import sys
import shutil
import subprocess
from datetime import datetime


VERSION = "1.0"
ERROR_FILE = "error.txt"


# ============================================================
# ERROR LOG
# ============================================================

def log_error(message):
    try:
        with open(ERROR_FILE, "a", encoding="utf-8") as f:
            f.write("\n")
            f.write("=" * 78 + "\n")
            f.write(
                f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]\n"
            )
            f.write(message.rstrip() + "\n")
            f.write("=" * 78 + "\n")
    except Exception:
        pass


# ============================================================
# READ MULTI-LINE UNTIL PATCH_END
# ============================================================

def read_patch():
    print()
    print("=" * 78)
    print("📋 PASTE PATCH DI SINI")
    print("=" * 78)
    print()
    print("Setelah semua block selesai, ketik:")
    print("PATCH_END")
    print()

    lines = []

    while True:
        try:
            line = input()
        except KeyboardInterrupt:
            print("\n❌ Dibatalkan.")
            sys.exit(0)
        except EOFError:
            break

        if line == "PATCH_END":
            break

        lines.append(line)

    return "\n".join(lines)


# ============================================================
# EXTRACT SECTION
# ============================================================

def extract_section(block, name):
    start = f"[{name}]"
    end = f"[/{name}]"

    if start not in block:
        return None

    if end not in block:
        raise ValueError(
            f"Section {start} tidak mempunyai {end}"
        )

    value = block.split(start, 1)[1].split(end, 1)[0]

    # Hanya buang newline kosong di luar.
    return value.strip("\n")


# ============================================================
# PARSE BLOCKS
# ============================================================

def parse_patch(text):

    raw_blocks = []
    current = []

    for line in text.splitlines():

        if line.strip().startswith("### "):

            if current:
                raw_blocks.append("\n".join(current))

            current = [line]

        else:
            current.append(line)

    if current:
        raw_blocks.append("\n".join(current))

    blocks = []

    for number, raw in enumerate(raw_blocks, 1):

        first_line = raw.splitlines()[0].strip()

        operation = first_line[4:].strip().upper()

        block = {
            "number": number,
            "operation": operation,
            "find": extract_section(raw, "FIND"),
            "for": extract_section(raw, "FOR"),
            "replace": extract_section(raw, "REPLACE"),
            "code": extract_section(raw, "CODE"),
            "line": extract_section(raw, "LINE"),
            "start": extract_section(raw, "START"),
            "end": extract_section(raw, "END"),
        }

        blocks.append(block)

    return blocks


# ============================================================
# FIND OCCURRENCES
# ============================================================

def find_all(text, target):

    positions = []
    start = 0

    while True:

        pos = text.find(target, start)

        if pos == -1:
            break

        positions.append(pos)

        start = pos + 1

    return positions


# ============================================================
# LINE INFORMATION
# ============================================================

def line_number(text, position):
    return text.count("\n", 0, position) + 1


def get_line(text, position):

    start = text.rfind("\n", 0, position) + 1

    end = text.find("\n", position)

    if end == -1:
        end = len(text)

    return text[start:end]


# ============================================================
# DUPLICATE REPORT
# ============================================================

def duplicate_report(
    filename,
    text,
    block,
    positions
):

    number = block["number"]
    find = block["find"]
    for_text = block["for"]

    out = []

    out.append(
        f"BLOCK #{number}: DUPLICATE FIND"
    )

    out.append(
        f"File: {filename}"
    )

    out.append(
        f"Jumlah kandidat: {len(positions)}"
    )

    out.append("")
    out.append("FIND:")
    out.append(find)

    if for_text:
        out.append("")
        out.append("FOR:")
        out.append(for_text)

    out.append("")
    out.append("KANDIDAT:")

    for i, pos in enumerate(positions, 1):

        out.append(
            f"[{i}] Line {line_number(text, pos)}:"
        )

        out.append(
            f"    {get_line(text, pos)}"
        )

    return "\n".join(out)


# ============================================================
# RESOLVE FIND
# ============================================================

def resolve_find(
    filename,
    text,
    block
):

    find = block["find"]

    if not find:
        return None, "FIND kosong."

    positions = find_all(text, find)

    # --------------------------------------------------------
    # NOT FOUND
    # --------------------------------------------------------

    if len(positions) == 0:

        message = (
            f"BLOCK #{block['number']}: FIND TIDAK DITEMUKAN\n"
            f"File: {filename}\n\n"
            f"FIND:\n{find}"
        )

        return None, message

    # --------------------------------------------------------
    # EXACTLY ONE
    # --------------------------------------------------------

    if len(positions) == 1:

        return positions[0], None

    # --------------------------------------------------------
    # DUPLICATE + FOR
    # --------------------------------------------------------

    for_text = block["for"]

    if not for_text:

        return None, duplicate_report(
            filename,
            text,
            block,
            positions
        )

    selected = []

    for pos in positions:

        line = get_line(text, pos)

        if for_text in line:
            selected.append(pos)

    # --------------------------------------------------------
    # FOR NOT FOUND
    # --------------------------------------------------------

    if len(selected) == 0:

        report = duplicate_report(
            filename,
            text,
            block,
            positions
        )

        report += (
            "\n\nFOR tidak cocok dengan kandidat mana pun."
        )

        return None, report

    # --------------------------------------------------------
    # FOR STILL DUPLICATE
    # --------------------------------------------------------

    if len(selected) > 1:

        report = duplicate_report(
            filename,
            text,
            block,
            selected
        )

        report += (
            "\n\nFOR masih menghasilkan "
            f"{len(selected)} kandidat."
        )

        return None, report

    # --------------------------------------------------------
    # ONE SELECTED
    # --------------------------------------------------------

    return selected[0], None


# ============================================================
# REPLACE
# ============================================================

def operation_replace(
    filename,
    text,
    block
):

    pos, error = resolve_find(
        filename,
        text,
        block
    )

    if error:
        return text, False, error

    find = block["find"]
    replace = block["replace"] or ""

    result = (
        text[:pos]
        + replace
        + text[pos + len(find):]
    )

    return result, True, None


# ============================================================
# DELETE
# ============================================================

def operation_delete(
    filename,
    text,
    block
):

    pos, error = resolve_find(
        filename,
        text,
        block
    )

    if error:
        return text, False, error

    find = block["find"]

    result = (
        text[:pos]
        + text[pos + len(find):]
    )

    return result, True, None


# ============================================================
# INSERT BEFORE / AFTER
# ============================================================

def operation_insert(
    filename,
    text,
    block,
    after=False
):

    pos, error = resolve_find(
        filename,
        text,
        block
    )

    if error:
        return text, False, error

    code = block["code"] or ""

    find = block["find"]

    if after:

        insert_at = pos + len(find)

        result = (
            text[:insert_at]
            + "\n"
            + code
            + text[insert_at:]
        )

    else:

        result = (
            text[:pos]
            + code
            + "\n"
            + text[pos:]
        )

    return result, True, None


# ============================================================
# INSERT LINE
# ============================================================

def operation_insert_line(
    text,
    block
):

    try:
        number = int(block["line"])
    except (TypeError, ValueError):

        return text, False, (
            f"BLOCK #{block['number']}: "
            "LINE tidak valid."
        )

    if number < 1:

        return text, False, (
            f"BLOCK #{block['number']}: "
            "LINE harus >= 1."
        )

    code = block["code"] or ""

    lines = text.splitlines(True)

    index = min(
        number - 1,
        len(lines)
    )

    lines.insert(
        index,
        code.rstrip("\n") + "\n"
    )

    return "".join(lines), True, None


# ============================================================
# DELETE LINE RANGE
# ============================================================

def operation_delete_lines(
    text,
    block
):

    try:

        start = int(block["start"])
        end = int(block["end"])

    except (TypeError, ValueError):

        return text, False, (
            f"BLOCK #{block['number']}: "
            "START/END tidak valid."
        )

    if start < 1 or end < start:

        return text, False, (
            f"BLOCK #{block['number']}: "
            "range line tidak valid."
        )

    lines = text.splitlines(True)

    if start > len(lines):

        return text, False, (
            f"BLOCK #{block['number']}: "
            f"START line {start} berada "
            f"di luar file ({len(lines)} lines)."
        )

    del lines[start - 1:end]

    return "".join(lines), True, None


# ============================================================
# APPLY ONE OPERATION
# ============================================================

def apply_operation(
    filename,
    text,
    block
):

    operation = block["operation"]

    if operation == "REPLACE":

        return operation_replace(
            filename,
            text,
            block
        )

    if operation == "DELETE":

        return operation_delete(
            filename,
            text,
            block
        )

    if operation == "INSERT_BEFORE":

        return operation_insert(
            filename,
            text,
            block,
            after=False
        )

    if operation == "INSERT_AFTER":

        return operation_insert(
            filename,
            text,
            block,
            after=True
        )

    if operation == "INSERT_LINE":

        return operation_insert_line(
            text,
            block
        )

    if operation == "DELETE_LINES":

        return operation_delete_lines(
            text,
            block
        )

    return text, False, (
        f"BLOCK #{block['number']}: "
        f"Operasi tidak dikenal: {operation}"
    )


# ============================================================
# PYTHON SYNTAX CHECK
# ============================================================

def syntax_check(filename):

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "py_compile",
            filename
        ],
        capture_output=True,
        text=True
    )

    return (
        result.returncode == 0,
        result.stderr
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("╔" + "═" * 76 + "╗")
    print("║" + " PYTHON MULTI-BLOCK PATCH TOOL v1.0".center(76) + "║")
    print("║" + " REPLACE • INSERT • DELETE • FOR • ERROR LOG".center(76) + "║")
    print("╚" + "═" * 76 + "╝")
    print()

    # --------------------------------------------------------
    # FILE
    # --------------------------------------------------------

    if len(sys.argv) >= 2:

        filename = sys.argv[1]

    else:

        filename = input(
            "📂 File Python: "
        ).strip()

    if not filename:

        print("❌ File kosong.")
        return

    if not os.path.isfile(filename):

        message = (
            f"File tidak ditemukan: {filename}"
        )

        print("❌", message)
        log_error(message)
        return

    # --------------------------------------------------------
    # READ FILE
    # --------------------------------------------------------

    try:

        with open(
            filename,
            "r",
            encoding="utf-8"
        ) as f:

            original = f.read()

    except Exception as e:

        message = (
            f"Gagal membaca {filename}: "
            f"{repr(e)}"
        )

        print("❌", message)
        log_error(message)
        return

    print(
        f"📄 File: {filename}"
    )

    print(
        f"📏 Lines: {len(original.splitlines())}"
    )

    # --------------------------------------------------------
    # PATCH
    # --------------------------------------------------------

    patch_text = read_patch()

    if not patch_text.strip():

        print("❌ Patch kosong.")
        return

    # --------------------------------------------------------
    # PARSE
    # --------------------------------------------------------

    try:

        blocks = parse_patch(
            patch_text
        )

    except Exception as e:

        message = (
            f"Gagal parse patch: {repr(e)}"
        )

        print("❌", message)
        log_error(message)
        return

    if not blocks:

        print("❌ Tidak ada block.")
        return

    print()
    print(
        f"📦 {len(blocks)} block ditemukan."
    )

    # --------------------------------------------------------
    # DRY RUN
    # --------------------------------------------------------

    working = original

    successful = []
    skipped = []

    print()
    print("=" * 78)
    print("🔍 DRY RUN")
    print("=" * 78)

    for block in blocks:

        number = block["number"]
        operation = block["operation"]

        print()
        print(
            f"BLOCK #{number} → {operation}"
        )

        new_text, ok, error = apply_operation(
            filename,
            working,
            block
        )

        if not ok:

            print("   ⚠️ SKIP")

            print()
            print(error)

            log_error(error)

            skipped.append(
                block
            )

            # ------------------------------------------------
            # PENTING:
            # block bermasalah dilewati.
            # block lain tetap jalan.
            # ------------------------------------------------

            continue

        working = new_text

        successful.append(
            block
        )

        print("   ✅ OK")

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    print()
    print("=" * 78)
    print("📋 SUMMARY")
    print("=" * 78)

    print(
        f"Total   : {len(blocks)}"
    )

    print(
        f"Berhasil: {len(successful)}"
    )

    print(
        f"Skip    : {len(skipped)}"
    )

    if skipped:

        print()
        print(
            "⚠️ Block yang dilewati:"
        )

        for block in skipped:

            print(
                f"   #{block['number']} "
                f"{block['operation']}"
            )

    # --------------------------------------------------------
    # NOTHING CHANGED
    # --------------------------------------------------------

    if not successful:

        print()
        print(
            "❌ Tidak ada perubahan yang valid."
        )

        return

    # --------------------------------------------------------
    # CONFIRM
    # --------------------------------------------------------

    print()

    answer = input(
        "🚀 Terapkan block yang valid? [y/N]: "
    ).strip().lower()

    if answer != "y":

        print(
            "❌ Dibatalkan."
        )

        return

    # --------------------------------------------------------
    # BACKUP
    # --------------------------------------------------------

    backup = filename + ".bak"

    try:

        shutil.copy2(
            filename,
            backup
        )

        print(
            f"💾 Backup: {backup}"
        )

    except Exception as e:

        message = (
            f"Gagal membuat backup: "
            f"{repr(e)}"
        )

        print("❌", message)
        log_error(message)
        return

    # --------------------------------------------------------
    # WRITE
    # --------------------------------------------------------

    try:

        with open(
            filename,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(working)

    except Exception as e:

        message = (
            f"Gagal menulis file: "
            f"{repr(e)}"
        )

        print("❌", message)

        log_error(message)

        try:
            shutil.copy2(
                backup,
                filename
            )
        except Exception:
            pass

        return

    # --------------------------------------------------------
    # SYNTAX CHECK
    # --------------------------------------------------------

    print()
    print(
        "🐍 Checking Python syntax..."
    )

    ok, error = syntax_check(
        filename
    )

    if not ok:

        print()
        print(
            "❌ SYNTAX ERROR"
        )

        print(error)

        log_error(
            "SYNTAX ERROR setelah patch:\n"
            + error
        )

        print()
        print(
            "↩️ Rollback..."
        )

        try:

            shutil.copy2(
                backup,
                filename
            )

            print(
                "✅ File di-restore."
            )

        except Exception as e:

            print(
                "❌ Restore gagal."
            )

            log_error(
                f"Restore gagal: {repr(e)}"
            )

        return

    # --------------------------------------------------------
    # SUCCESS
    # --------------------------------------------------------

    print()
    print("╔" + "═" * 76 + "╗")
    print(
        "║" +
        " ✅ PATCH SELESAI".center(76) +
        "║"
    )
    print("╚" + "═" * 76 + "╝")

    print()
    print(
        f"📄 File       : {filename}"
    )

    print(
        f"✅ Applied    : {len(successful)}"
    )

    print(
        f"⚠️ Skipped    : {len(skipped)}"
    )

    print(
        f"💾 Backup     : {backup}"
    )

    print(
        "🐍 Syntax     : OK"
    )

    if skipped:

        print()
        print(
            "📝 Detail block yang skip:"
        )

        print(
            f"   {ERROR_FILE}"
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as e:

        message = (
            "UNHANDLED ERROR\n"
            + repr(e)
        )

        print(
            "\n❌",
            message
        )

        log_error(message)
