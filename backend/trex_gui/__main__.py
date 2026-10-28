# Keep top-level imports minimal: worker processes are started with "spawn",
# which re-imports this module. Anything imported here would be loaded before
# the TRex client's bundled libraries (yaml, scapy, zmq) in every worker.
import argparse


def main():
    parser = argparse.ArgumentParser(prog="trex-gui", description="TRex stateless web GUI")
    parser.add_argument("-c", "--config", default="config.yaml", help="path to config file")
    parser.add_argument("--host", help="override server.host")
    parser.add_argument("--port", type=int, help="override server.port")
    args = parser.parse_args()

    import uvicorn

    from .affinity import apply_cpu_affinity
    from .app import create_app
    from .config import load_config

    config = load_config(args.config)
    if args.host:
        config.server.host = args.host
    if args.port:
        config.server.port = args.port

    apply_cpu_affinity(config)

    uvicorn.run(create_app(config), host=config.server.host, port=config.server.port)


if __name__ == "__main__":
    main()
