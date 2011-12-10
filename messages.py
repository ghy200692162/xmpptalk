import logging
from functools import wraps
import datetime

import commands
import config
import logdb
from models import connection
from misc import *

'''message handling

This module supports extending by the following means:

It will try to get two iterables from the plugin package with the names
`message_plugin_early` and `message_plugin`. Each message handler in
`message_plugin_early` will be executed *before* standard handling, and those in
`message_plugin` will be executed *after* standard handling.

Message handlers accept two argument: the bot itself and the message string.
If the handler returns `True`, no further actions are done; if `str`, it's
the new message that will be handled later.
'''

logger = logging.getLogger(__name__)
_message_handles = []

def message_handler_register(func):
  '''register a message handler

  use a register func instead of decorator so that it's easier to (re-)order
  the handlers'''
  _message_handles.append(func)

def pingpong(self, msg):
  '''availability test'''
  if msg == 'ping':
    self.reply('pong')
    self.user_reset_stop()
    return True
  return False

def command(self, msg):
  return commands.handle_command(self, msg)

def filter_otr(self, msg):
  if msg.startswith('?OTR'):
    self.reply(_('Your client is trying OTR encryption, which is not supported by this group.'))
    return True
  else:
    return False

def give_help(self, msg):
  '''special handling for help messages'''
  if config.help_regex.match(msg):
    return commands.handle_command(self, 'help')
  else:
    return False

def check_auth(self, msg):
  '''check if the user has joined or not'''
  bare = self.current_jid.bare()
  subscribers = [x.jid for x in self.roster if x.subscription == 'both']
  if bare in subscribers:
    return False

  if config.private:
    self.reply(_('You are not allowed to send messages to this group until invited'))
  else:
    self.reply(_('You are currently not joined in this group, message ignored'))
    self.xmpp_add_user(bare)
  return True

class MessageMixin:
  def handle_message(self, msg, timestamp=None):
    '''apply handlers; timestamp indicates a delayed messages'''
    for h in _message_handles:
      ret = h(self, msg)
      if ret is True:
        break
      elif isinstance(ret, str):
        msg = ret
    else:
      self.user_update_msglog(msg)
      msg = '[%s] ' % self.user_get_nick(str(self.current_jid.bare())) + msg
      self.user_reset_stop() # self.current_user is reloaded here
      self.dispatch_message(msg, timestamp)

  def dispatch_message(self, msg, timestamp=None):
    '''dispatch message to group members, also log the message in database'''
    jid = self.current_user.jid

    if timestamp:
      dt = datetime.datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%SZ')
      interval = NOW() - dt
      if interval.days == 0:
        dt += config.timezoneoffset
        msg = '(%s) ' % dt.strftime(timeformat) + msg

    logdb.logmsg(self.current_jid, msg)
    for u in self.get_message_receivers():
      if u != jid:
        self.send_message(u, msg)
    return True

  def get_message_receivers(self):
    allusers = {u['jid'] for u in connection.User.find({
      'stop_until': {'$lte': NOW()}
    }, ['jid'])}
    return [u for u in self.get_online_users() if str(u) in allusers]

try:
  from plugin import message_plugin_early
  for h in message_plugin_early:
    message_handler_register(h)
except ImportError:
  pass

# these are standard message plugins that normally desired
message_handler_register(check_auth)
message_handler_register(pingpong)
message_handler_register(give_help)
message_handler_register(command)
message_handler_register(filter_otr)

try:
  from plugin import message_plugin
  for h in message_plugin:
    message_handler_register(h)
except ImportError:
  pass
