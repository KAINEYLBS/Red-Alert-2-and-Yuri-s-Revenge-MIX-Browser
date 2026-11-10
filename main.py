from mix_browser.app.application import run


# @arch mix-browser.desktop-script-entrypoint entrypoint | en: Starts the desktop application from the project script | zh: 从项目脚本启动桌面应用
def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
