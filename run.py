import multiprocessing

if __name__ == '__main__':
    multiprocessing.freeze_support()     # needed for export worker processes in the packaged app
    from motion_studio.app import main
    main()
