import argparse
from ocr.ocr_engine import extract_text


def main():
    parser = argparse.ArgumentParser(description="Invoice OCR to text")
    parser.add_argument("--input", required=True, help="Path to invoice PDF or image")
    parser.add_argument("--output", default="outputs/raw_text.txt", help="Path to save extracted text")

    args = parser.parse_args()

    print("[*] Extracting text from invoice...")
    text = extract_text(args.input)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(text)

    print(f"[+] OCR complete. Text saved to: {args.output}")


if __name__ == "__main__":
    main()
