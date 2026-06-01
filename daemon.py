import time
from foo import get_gpu_temp, set_fan, curve

MAX = 4400

while True:
    gpu_temp = get_gpu_temp()

    if gpu_temp > 95:
        set_fan(MAX)

    else:
        set_fan(curve(gpu_temp))

    time.sleep(3)