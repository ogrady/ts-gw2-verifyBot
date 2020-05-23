#!/usr/bin/python
import ts3 #teamspeak library
import time #time for sleep function
import re #regular expressions
import TS3Auth #includes datetime import
import sqlite3 #Database
import os #operating system commands -check if files exist
import datetime #for date strings
import schedule # Allows auditing of users every X days
from bot_messages import * #Import all Static messages the BOT may need
from TS3Bot import *
from threading import Thread
import sys
import ipc

#######################################
# Begins the connect to Teamspeak
#######################################
default_server_group_id = -1

bot_loop_forever=True
TS3Auth.log("Initializing script....")
while bot_loop_forever:
    try:    
        TS3Auth.log("Connecting to Teamspeak server...")
        with ThreadsafeTSConnection(Config.user
                                    , Config.passwd
                                    , Config.host
                                    , Config.port
                                    , Config.keepalive_interval
                                    , Config.server_id
                                    , Config.bot_nickname) as ts3conn:         
            BOT=Bot(Config.db_file_name, ts3conn, Config.verified_group, Config.bot_nickname)
            IPCS=ipc.TwistedServer(Config.ipc_port, ts3conn, client_message_handler = BOT.client_message_handler)

            ipcthread = Thread(target = IPCS.run)
            ipcthread.daemon = True
            ipcthread.start() 
            TS3Auth.log ("BOT loaded into server (%s) as %s (%s). Nickname '%s'" %(Config.server_id, BOT.name, BOT.client_id, BOT.nickname))

            # Find the verify channel
            verify_channel_id=0
            while verify_channel_id == 0:
                channel, ex = ts3conn.ts3exec(lambda tc: tc.query("channelfind", pattern=Config.channel_name).first(), signal_exception_handler)
                if ex:
                    TS3Auth.log ("Unable to locate channel with name '%s'. Sleeping for 10 seconds..." % (Config.channel_name,))
                    time.sleep(10)
                else:
                    verify_channel_id=channel.get("cid")
                    channel_name=channel.get("channel_name")                  

            # Find the verify group ID
            verified_group_id = BOT.groupFind(Config.verified_group)

            # Find default server group
            default_server_group_id, ex = ts3conn.ts3exec(lambda tc: tc.query("serverinfo").first().get("virtualserver_default_server_group"))

            # Move ourselves to the Verify chanel and register for text events
            _, chnl_err = ts3conn.ts3exec(lambda tc: tc.exec_("clientmove", clid=BOT.client_id, cid=verify_channel_id))
            if chnl_err:
                TS3Auth.log("BOT Attempted to join channel '%s' (%s) WARN: %s" % (Config.channel_name, verify_channel_id, chnl_err.resp.error["msg"]))
            else:
                TS3Auth.log ("BOT has joined channel '%s' (%s)." % (Config.channel_name, verify_channel_id))             
            
            ts3conn.ts3exec(lambda tc: tc.exec_("servernotifyregister", event="textchannel")) #alert channel chat
            ts3conn.ts3exec(lambda tc: tc.exec_("servernotifyregister", event="textprivate")) #alert Private chat
            ts3conn.ts3exec(lambda tc: tc.exec_("servernotifyregister", event="server"))

            #Send message to the server that the BOT is up
            # ts3conn.exec_("sendtextmessage", targetmode=3, target=server_id, msg=locale.get("bot_msg",(bot_nickname,)))
            TS3Auth.log("BOT is now registered to receive messages!")

            TS3Auth.log("BOT Database Audit policies initiating.")
            # Always audit users on initialize if user audit date is up (in case the script is reloaded several times before audit interval hits, so we can ensure we maintain user database accurately)
            BOT.auditUsers()

            #Set audit schedule job to run in X days
            schedule.every(Config.audit_interval).days.do(BOT.auditUsers)

            #Since v2 of the ts3 library, keepalive must be sent manually to not screw with threads
            schedule.every(Config.keepalive_interval).seconds.do(lambda: ts3conn.ts3exec(lambda tc: tc.send_keepalive))

            commander_checker = CommanderChecker(BOT, IPCS, Config.poll_group_names, Config.poll_group_poll_delay)

            #Set schedule to advertise broadcast message in channel
            if Config.timer_msg_broadcast > 0:
                    schedule.every(Config.timer_msg_broadcast).seconds.do(BOT.broadcastMessage)
            BOT.broadcastMessage() # Send initial message into channel

            # debug
            """
            BOT.setResetroster(ts3conn, "2020-04-01", red = ["the name with the looooong name"], green = ["another really well hung name", "len", "oof. tat really a long one duuuude"], blue = ["[DUST] dude", "[DUST] anotherone", "[DUST] thecrusty dusty mucky man"], ebg = [])
            """
            # testguilds = [("Sxxxtxxxxxxxmxxxxxwxyxxx", "sdassdas", "assdsss")
            #             , ("Requiem of Execution", "RoE", "RoE")
            #             , ("Formation Wolke", "Zerg", "Zerg.")
            #             , ("Zergs Rebellion", "Zerg", "Zerg")
            #             , ("Rising River", "Side", "Side")
            #             , ("Zum Henker", "ZH", "ZH")]
            # 
            # for gname, gtag, ggroup in testguilds:
            #     BOT.removeGuild(gname, gtag, ggroup)
            #     BOT.createGuild(gname, gtag, ggroup, ["len.1879", "jey.1111"])
            


            #Forces script to loop forever while we wait for events to come in, unless connection timed out. Then it should loop a new bot into creation.
            TS3Auth.log("BOT now idle, waiting for requests.")
            while ts3conn.ts3exec(lambda tc: tc.is_connected(), signal_exception_handler)[0]:
                #auditjob + keepalive check
                schedule.run_pending()
                event, ex = ts3conn.ts3exec(lambda tc: tc.wait_for_event(timeout=Config.bot_sleep_idle), ignore_exception_handler)
                if event:
                    try:
                        if "msg" in event.parsed[0]:
                            # text message
                            BOT.message_event_handler(event) # handle event
                        elif "reasonmsg" in event.parsed[0]:
                            # user left
                            pass
                        else:
                            BOT.login_event_handler(event)
                    except Exception as ex:
                        TS3Auth.log("Error while trying to handle event %s: %s" % (str(event), str(ex)))

        TS3Auth.log("It appears the BOT has lost connection to teamspeak. Trying to restart connection in %s seconds...." % Config.bot_sleep_conn_lost)
        time.sleep(Config.bot_sleep_conn_lost)

    except (ConnectionRefusedError, ts3.query.TS3TransportError):
        TS3Auth.log("Unable to reach teamspeak server..trying again in %s seconds..." % Config.bot_sleep_conn_lost)
        time.sleep(Config.bot_sleep_conn_lost)
    except (KeyboardInterrupt, SystemExit):
        bot_loop_forever = False
        sys.exit(0)

#######################################
