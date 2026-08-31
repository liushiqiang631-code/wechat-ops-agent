import sys

from app.cli import main

if __name__ == "__main__":
    arguments = ["probe-wechat", *sys.argv[1:]]
    raise SystemExit(main(arguments))
