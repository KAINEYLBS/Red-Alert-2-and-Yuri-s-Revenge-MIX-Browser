import sys


# @arch mix-browser.desktop-script-entrypoint entrypoint | en: Starts the desktop application from the project script | zh: 从项目脚本启动桌面应用
def main() -> int:
    arguments = sys.argv[1:]
    if arguments[:1] == ["--basic-mode"]:
        from mix_browser.app.basic_mode import run_basic_mode

        return run_basic_mode(arguments[1:])
    if arguments[:1] == ["--progress-helper"]:
        from mix_browser.shared.progress_helper import main as run_progress_helper

        return run_progress_helper()
    from mix_browser.app.application import run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
