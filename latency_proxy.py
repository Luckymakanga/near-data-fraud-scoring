"""
LATENCY PROXY
A TCP relay that adds a fixed delay in each direction

Putting this between the application and PostgreSQL adds network distance
without a second machine: the application connects to the proxy's port, the
proxy forwards every byte to the database and back, and each chunk is held
for `one_way_ms` before it is passed on. A query and its reply therefore
cost an extra round trip of 2 x one_way_ms.

What it models: fixed latency. It does not model bandwidth limits, jitter or
packet loss, and the relay itself adds a little delay of its own (a fraction
of a millisecond), so callers should measure the round trip actually
obtained (measure_round_trip) rather than trust the setting.

Windows' default timer ticks about every 15 ms, which would round small
delays up, so on Windows the relay asks for 1 ms timer resolution.

Usage as a library:
    proxy = start_proxy(listen_port=5440, target=('localhost', 5433), one_way_ms=5)
    ... connect to localhost:5440 ...
    proxy.terminate()

Usage from the command line (for trying it out):
    python latency_proxy.py --listen 5440 --target-port 5433 --one-way-ms 5
"""

import argparse
import asyncio
import multiprocessing
import socket
import statistics
import sys
import time


def _request_fine_timer():
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.winmm.timeBeginPeriod(1)


async def _pipe(reader, writer, delay):
    """Copy reader to writer, releasing each chunk `delay` seconds after it arrived"""
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()

    async def release():
        while True:
            item = await queue.get()
            if item is None:
                break
            due, data = item
            wait = due - loop.time()
            if wait > 0:
                await asyncio.sleep(wait)
            writer.write(data)
            await writer.drain()
        writer.close()

    releaser = asyncio.create_task(release())
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            queue.put_nowait((loop.time() + delay, data))
    except (ConnectionError, OSError):
        pass
    finally:
        queue.put_nowait(None)
        try:
            await releaser
        except (ConnectionError, OSError):
            pass


async def _serve(listen_port, target, one_way_ms, ready):
    delay = one_way_ms / 1000

    async def handle(client_reader, client_writer):
        try:
            server_reader, server_writer = await asyncio.open_connection(*target)
        except OSError:
            client_writer.close()
            return
        for sock_writer in (client_writer, server_writer):
            sock = sock_writer.get_extra_info('socket')
            if sock is not None:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        await asyncio.gather(
            _pipe(client_reader, server_writer, delay),
            _pipe(server_reader, client_writer, delay),
        )

    server = await asyncio.start_server(handle, '127.0.0.1', listen_port)
    if ready is not None:
        ready.set()
    async with server:
        await server.serve_forever()


def run_proxy(listen_port, target, one_way_ms, ready=None):
    _request_fine_timer()
    asyncio.run(_serve(listen_port, target, one_way_ms, ready))


def start_proxy(listen_port, target, one_way_ms):
    """Start the relay in its own process and return once it is accepting connections"""
    ready = multiprocessing.Event()
    process = multiprocessing.Process(
        target=run_proxy, args=(listen_port, target, one_way_ms, ready),
        name=f'latency proxy {listen_port}', daemon=True)
    process.start()
    if not ready.wait(timeout=15):
        process.terminate()
        raise RuntimeError('latency proxy did not start')
    return process


def measure_round_trip(dsn, samples=100):
    """Median and 95th-percentile time for a trivial query, in milliseconds"""
    import psycopg2
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    cur = conn.cursor()
    for _ in range(10):  # warm up
        cur.execute('SELECT 1')
        cur.fetchone()
    times = []
    for _ in range(samples):
        started = time.perf_counter()
        cur.execute('SELECT 1')
        cur.fetchone()
        times.append((time.perf_counter() - started) * 1000)
    conn.close()
    times.sort()
    return {'median_ms': statistics.median(times), 'p95_ms': times[int(0.95 * len(times)) - 1]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='TCP relay with added latency')
    parser.add_argument('--listen', type=int, default=5440)
    parser.add_argument('--target-host', default='localhost')
    parser.add_argument('--target-port', type=int, default=5433)
    parser.add_argument('--one-way-ms', type=float, default=5)
    args = parser.parse_args()
    print(f'relaying 127.0.0.1:{args.listen} -> {args.target_host}:{args.target_port}'
          f' with {args.one_way_ms:g} ms each way')
    run_proxy(args.listen, (args.target_host, args.target_port), args.one_way_ms)
