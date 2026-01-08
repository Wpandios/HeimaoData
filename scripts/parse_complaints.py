import argparse
import csv
import logging
import os
import re
from datetime import datetime

def normalize_date(s: str) -> str:
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%Y-%m-%d")
    except Exception:
        return s

def extract_amounts(text: str):
    amounts = re.findall(r"(\d+(?:\.\d+)?)\s*元", text)
    return [a for a in amounts]

def normalize_request(req: str) -> str:
    if not req:
        return ""
    parts = re.split(r"[，,、/\s]+", req)
    mapped = []
    for p in parts:
        t = p.strip()
        if not t:
            continue
        if t in {"退钱", "退费", "退回所扣费用"}:
            t = "退款"
        mapped.append(t)
    return ";".join(mapped)

def finalize_record(current, source_file: str, index: int):
    desc = "\n".join(current.get("description_lines", []))
    req = normalize_request(current.get("complaint_request_raw", ""))
    amt = extract_amounts((current.get("title", "") + " " + desc))
    return {
        "date": current.get("date", ""),
        "title": current.get("title", ""),
        "description": desc,
        "complaint_object": current.get("complaint_object", ""),
        "complaint_request": req,
        "status": current.get("status", ""),
        "amount_list": ";".join(amt),
        "source_file": source_file,
        "block_index": index,
    }

def parse_file(path: str):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    date_line_pat = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+于黑猫投诉平台发起$", re.M)
    status_set = {"已回复", "处理中", "待分配"}
    records = []
    matches = list(date_line_pat.finditer(content))
    for idx, m in enumerate(matches):
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
        block = content[start:end].strip()
        block_lines = [l.strip() for l in block.splitlines()]
        invalid_code_pat = re.compile(r"^\d{3}$")
        invalid_alias_pat = re.compile(r"^[\u4e00-\u9fa5]{1,6}喵$")
        cleaned = [block_lines[0]] + [l for l in block_lines[1:] if not (invalid_code_pat.match(l) or invalid_alias_pat.match(l))]
        block_lines = cleaned
        date_str = normalize_date(m.group(1))
        title = ""
        i = 1
        while i < len(block_lines) and not block_lines[i]:
            i += 1
        if i < len(block_lines):
            title = block_lines[i]
            i += 1
        complaint_object = ""
        complaint_request_raw = ""
        status = ""
        for l in block_lines[i:]:
            if l.startswith("[投诉对象]"):
                complaint_object = l.replace("[投诉对象]", "").strip()
            elif l.startswith("[投诉要求]"):
                complaint_request_raw = l.replace("[投诉要求]", "").strip()
            elif l in status_set:
                status = l
        description_lines = []
        for l in block_lines[i:]:
            if l.startswith("[投诉对象]") or l.startswith("[投诉要求]") or (l in status_set):
                continue
            if l:
                description_lines.append(l)
        records.append(finalize_record({
            "date": date_str,
            "title": title,
            "description_lines": description_lines,
            "complaint_object": complaint_object,
            "complaint_request_raw": complaint_request_raw,
            "status": status,
        }, path, idx + 1))
    logging.info("records parsed: %d", len(records))
    logging.info("records with object: %d", sum(1 for r in records if r.get("complaint_object")))
    logging.info("records with request: %d", sum(1 for r in records if r.get("complaint_request_raw")))
    logging.info("records with status: %d", sum(1 for r in records if r.get("status")))
    return records

def write_csv(records, output_path: str):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fieldnames = [
        "date",
        "title",
        "description",
        "complaint_object",
        "complaint_request",
        "status",
        "amount_list",
        "source_file",
        "block_index",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            writer.writerow(r)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--log", default="output/parse_rongbei.log")
    args = parser.parse_args()
    os.makedirs(os.path.dirname(args.log), exist_ok=True)
    logging.basicConfig(filename=args.log, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        logging.info("start parse %s", args.input)
        records = parse_file(args.input)
        logging.info("records: %d", len(records))
        write_csv(records, args.output)
        logging.info("written csv to %s", args.output)
        print(args.output)
    except Exception as e:
        logging.exception("error")
        raise

if __name__ == "__main__":
    main()
