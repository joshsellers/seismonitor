import os
import random
import sys
import time

import pygame
from pygame.locals import *
from obspy.clients.seedlink import SLClient
from obspy.clients.seedlink.slpacket import SLPacket
from obspy import Stream, Trace, UTCDateTime
import threading
import logging
from tkinter import *
import numpy as np

import requests
from dotenv import load_dotenv

load_dotenv()
APP_TOKEN = os.getenv('APP_TOKEN')
USER_TOKEN = os.getenv('USER_TOKEN')

url = 'https://api.pushover.net/1/messages.json'
title = 'SeisMonitor'


def current_milli_time():
    return round(time.time() * 1000)


class Client(SLClient):
    def __init__(self, stream, myargs=None, lock=None):
        # loglevel NOTSET delegates messages to parent logger
        super(Client, self).__init__()
        self.stream = stream
        self.lock = lock
        self.args = myargs

    def packet_handler(self, count, slpack):
        print(f'packet in @{UTCDateTime()}')
        # check if not a complete packet
        if slpack is None or (slpack == SLPacket.SLNOPACKET) or \
                (slpack == SLPacket.SLERROR):
            return False

        # get basic packet info
        type = slpack.get_type()

        # process INFO packets here
        if type == SLPacket.TYPE_SLINF:
            return False
        if type == SLPacket.TYPE_SLINFT:
            logging.info("Complete INFO:" + self.slconn.getInfoString())
            if self.infolevel is not None:
                return True
            else:
                return False

        # process packet data
        trace = slpack.get_trace()
        if trace is None:
            logging.info(
                self.__class__.__name__ + ": blockette contains no trace")
            return False

        # new samples add to the main stream which is then trimmed
        with self.lock:
            self.stream += trace
            self.stream.merge(-1)
            for tr in self.stream:
                tr.stats.processing = []
        return False


    def getTraceIDs(self):
        """
        Return a list of SEED style Trace IDs that the SLClient is trying to
        fetch data for.
        """
        ids = []
        streams = self.slconn.get_streams()
        for stream in streams:
            net = stream.net
            sta = stream.station
            selectors = stream.get_selectors()
            for selector in selectors:
                if len(selector) == 3:
                    loc = ""
                else:
                    loc = selector[:2]
                cha = selector[-3:]
                ids.append(".".join((net, sta, loc, cha)))
        ids.sort()
        return ids


FRAME_RATE = 30
SCREEN_SIZE = (500, 500)
WORLD_SIZE = (500, 500)


def rgba_tuple_to_rgb_int(rgba):
    rgb = tuple(rgba[:-1])
    r = rgb[0]
    g = rgb[1]
    b = rgb[2]
    return (r << 16) + (g << 8) + b


def pygame_modules_have_loaded():
    success = pygame.display.get_init() and pygame.font.get_init() and pygame.mixer.get_init()
    return success


# pygame.mixer.pre_init(44100, -16, 2, 512)
pygame.init()
pygame.font.init()

if pygame_modules_have_loaded():
    screen = pygame.display.set_mode(SCREEN_SIZE)
    game_screen = pygame.Surface(WORLD_SIZE)
    pygame.display.set_caption("seismonitor")
    clock = pygame.time.Clock()
    pygame.show_fps = False


    def prep():
        pass


    def handle_input(key_name):
        if key_name == "escape":
            pygame.quit()
            sys.exit()
        elif key_name == "f3":
            pygame.show_fps = not pygame.show_fps
            

    AVERAGES = {}
    last_notification_time = 0
    capture_screen = False
    def update(game_screen, time, stream):
        global capture_screen
        global last_notification_time
        
        if capture_screen:
            pygame.image.save(screen, f"capture@{UTCDateTime()}.png")
            capture_screen = False
        
        pygame.draw.rect(game_screen, 0x000000, (0, 0, WORLD_SIZE[0], WORLD_SIZE[1]))

        traces = stream.traces

        midpoint = WORLD_SIZE[1] / 4 - 100
        spacing = 150
        for index in range(0, len(traces)):
            total = 0
            trace = traces[index]
            last_tr = 0
            c_time = WORLD_SIZE[0] - 100
            for i in range(len(trace) - 1, int(len(trace) / 2), -1):
                tr = trace[i]
                tr /= 100
                if "KIP" in trace.id:
                    tr /= 50
                
                total += tr
                
                time_step = 0.05
                pygame.draw.line(game_screen, 0xFFFFFF,
                                 (c_time + time_step, last_tr + midpoint + spacing * index),
                                 (c_time, tr + midpoint + spacing * index))
                last_tr = tr
                c_time -= time_step
                if c_time < 0:
                    break

                notification_threshold = 200
                try:
                    if abs(AVERAGES[trace.id] - tr) > notification_threshold\
                            and current_milli_time() - last_notification_time > 60 * 5 * 1000:
                        message = f'{LOCATIONS[trace.id]} breached threshold'
                        print(message)
                        pushover_req = {'token': APP_TOKEN, 'user': USER_TOKEN, 'title': title, 'message': message}
                        requests.post(url, data=pushover_req)
                        last_notification_time = current_milli_time()
                        
                        capture_screen = True
                except KeyError:
                    pass

            AVERAGES[trace.id] = total / len(trace)
            
            loc_font = pygame.font.SysFont('Courier New', 12)
            loc_label = loc_font.render(f'{trace.id} ({LOCATIONS[trace.id]})', False, (0xff, 0xff, 0xff), (0, 0, 0))
            screen.blit(loc_label, (10, midpoint + spacing * index))
        pygame.display.update()


    def main(stream):
        prep()

        while True:
            for event in pygame.event.get():
                if event.type == QUIT:
                    pygame.quit()
                    sys.exit()

                if event.type == KEYDOWN:
                    key_name = pygame.key.name(event.key)
                    handle_input(key_name)

            milliseconds = clock.tick(FRAME_RATE)
            seconds = milliseconds / 1000.0
            update(game_screen, seconds, stream)
            pygame.transform.scale(game_screen, SCREEN_SIZE, screen)

            if pygame.show_fps:
                fps_font = pygame.font.SysFont('Courier New', 12)
                fps_label = fps_font.render(f'{int(clock.get_fps())} fps', False, (0xff, 0xff, 0xff), (0, 0, 0))
                screen.blit(fps_label, (0, 0))
                pygame.display.update()

            sleep_time = (1000.0 / FRAME_RATE) - milliseconds
            if sleep_time > 0.0:
                pygame.time.wait((int(sleep_time)))
            else:
                pygame.time.wait(1)


LOCATIONS = {}

if __name__ == "__main__":
    now = UTCDateTime()
    stream = Stream()
    lock = threading.Lock()

    sl_client = Client(stream, lock=lock)
    #sl_client.slconn.set_sl_address("rtserver.ipgp.fr:18000")
    sl_client.slconn.set_sl_address("rtserve.iris.washington.edu:18000")
    # http://www.fdsn.org/networks/?initial=G
    sl_client.multiselect = "G_PEL:00BHZ,G_HDC:00BHZ,G_INU:00BHZ,G_KIP:00BHZ"
    LOCATIONS = {
        "G.HDC.00.BHZ": "Costa Rica",
        "G.INU.00.BHZ": "Japan",
        "G.PEL.00.BHZ": "Chile",
        "G.KIP.00.BHZ": "Hawaii"
    }

    sl_client.begin_time = (now - 600).format_seedlink()

    sl_client.initialize()
    # start cl in a thread
    thread = threading.Thread(target=sl_client.run)
    thread.setDaemon(True)
    thread.start()

    time.sleep(2)
    main(stream)
