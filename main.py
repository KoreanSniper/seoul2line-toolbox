if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test-report":
        from app.healthcheck import run
        raise SystemExit(run(sys.argv[2]))
    elif sys.argv[1:] == ["--run-gpu-stars"]:
        from app.tools.chill_starsystem_gpu import run_gpu_window
        run_gpu_window()
    else:
        from app.main_window import main
        main()
