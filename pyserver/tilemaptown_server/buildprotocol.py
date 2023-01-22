# Tilemap Town
# Copyright (C) 2017-2023 NovaSquirrel
#
# This program is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import json, datetime
from .buildglobal import *
from .buildcommand import handle_user_command, escape_tags, tile_is_okay, data_disallowed_for_entity_type
from .buildentity import Entity

handlers = {}
command_privilege_level = {} # minimum required privilege level required for the command; see user_privilege in buildglobal.py
map_only_commands = set()

# Adds a command handler
def protocol_command(privilege_level='guest', map_only=False):
	def decorator(f):
		command_name = f.__name__[3:]
		handlers[command_name] = f
		if map_only:
			map_only_commands.add(command_name)
		command_privilege_level[command_name] = privilege_level
	return decorator

# -------------------------------------

CLIENT_WHO_WHITELIST = {
	"typing": bool
}

def validate_client_who(id, data):
	validated_data = {"id": id}
	for key, value in data.items():
		if key in CLIENT_WHO_WHITELIST:
			validated_data[key] = CLIENT_WHO_WHITELIST[key](value)
	return validated_data

def must_be_map_owner(client, admin_okay, give_error=True):
	if client.map == None:
		return False
	if client.map.owner_id == self.db_id or self.oper_override or (admin_okay and self.has_permission(self, permission['admin'], False)):
		return True
	elif give_error:
		client.send("ERR", {'text': 'You don\'t have permission to do that'})
	return False

def must_be_server_admin(client, give_error=True):
	if not client.is_client():
		return False
	if client.username in Config["Server"]["Admins"]:
		return True
	elif give_error:
		client.send("ERR", {'text': 'You don\'t have permission to do that'})
	return False

# -------------------------------------

@protocol_command()
def fn_MOV(map, client, arg):
	# Can control a different entity if you have permission
	if 'rc' in arg:
		id = arg['rc']
		if not client.has_permission(id, (permission['move'], permission['move_new_map']), False):
			client.send("ERR", {'text': 'You don\'t have permission to move entity %s' % id})
			return
		entity = get_entity_by_id(id, load_from_db=False)
		if entity is not client: # Make sure it's not actually just the client supplying their own ID
			if entity == None:
				client.send("ERR", {'text': 'Can\'t move entity %s because it\'s not loaded' % id})
				return
			if entity.map == None:
				client.send("ERR", {'text': 'Can\'t move entity %s because it\'s not on a map' % id})
				return

			del arg['id']
			fn_MOV(entity.map, entity, arg)
			return

	# Controlling this entity
	data = {'id': client.protocol_id()}
	for valid_field in ('from', 'to', 'dir'):
		if valid_field in arg:
			data[valid_field] = arg[valid_field]
	map.broadcast("MOV", data, remote_category=botwatch_type['move'])

	new_dir = data['dir'] if 'dir' in data else None
	if 'to' in data:
		client.move_to(data['to'][0], data['to'][1], new_dir=new_dir)
	else:
		client.move_to(None, None, new_dir=new_dir)		

@protocol_command()
def fn_CMD(map, client, arg):
	actor = client
	echo = arg['echo'] if ('echo' in arg) else None

	if 'rc' in arg:
		if client.has_permission(arg['rc'], permission['remote_command'], False):
			actor = get_entity_by_id(arg['rc'], load_from_db=False)
			if actor == None:
				client.send("ERR", {'text': 'Entity %s not loaded' % arg['rc']})
		else:
			client.send("ERR", {'text': 'You don\'t have permission to remote control %s' % arg['rc']})

	handle_user_command(map, actor, client, echo, arg["text"])

@protocol_command()
def fn_TAK(map, client, arg):
	pass

@protocol_command()
def fn_DRO(map, client, arg):
	pass

@protocol_command()
def fn_BAG(map, client, arg):
	def allow_special_ids(text):
		if text == 'here':
			return map.db_id
		if text == 'me':
			return client.db_id
		return text

	if client.db_id != None:
		c = Database.cursor()
		if "create" in arg:
			# restrict type variable
			if arg['create']['type'] not in creatable_entity_types:
				client.send("ERR", {'text': 'Invalid type of item to create (%s)' % arg['create']['type']})
				return
			e = Entity(entity_type[arg['create']['type']], creator_id=client.db_id)
			e.name = arg['create']['name']
			e.map_id = client.db_id
			if 'temp' in arg['create'] and arg['create']['temp'] == True:
				e.temporary = True
			else:
				e.save()
			client.add_to_contents(e)

		elif "clone" in arg:
			clone_me = get_entity_by_id(allow_special_ids(arg['clone']))
			if clone_me == None:
				client.send("ERR", {'text': 'Can\'t clone %s' % arg['clone']})
				return

			if clone_me.owner_id != client.db_id and not client.has_permission(clone_me, permission['copy'], False):
				client.send("ERR", {'text': 'You don\'t have permission to clone %s' % arg['clone']})
				return

			# Create a new entity and copy over the properties
			new_item = Entity(clone_me.entity_type)
			clone_me.copy_onto(new_item)
			if 'temp' in arg['clone']: # Can change the temporary status
				if arg['clone']['temp'] == True:
					clone_me.temporary = True
				else:
					clone_me.temporary = False
			new_item.owner_id = client.db_id

			if not new_item.temporary:
				new_item.save()
			# Put it in the player's inventory now, or wherever else they put it
			if 'folder' in args['clone']:
				new_item.switch_map(args['clone']['folder'], new_pos=args['clone']['pos'] if 'pos' in args['clone'] else None)
			else:
				client.add_to_contents(new_item)

			# Update created_at and acquired_at
			if new_item.db_id:
				c.execute('SELECT created_at FROM Entity WHERE id=?', (arg['clone'],))
				result = c.fetchone()
				if result != None:
					c.execute('UPDATE Entity SET created_at=?, acquired_at=? WHERE id=?', (result[0], datetime.datetime.now(), new_item.db_id))

			arg["clone"]["new_id"] = new_item.protocol_id()
			client.send("BAG", {'clone': arg['clone']}) # Acknowledge

		elif "update" in arg:
			update = arg['update']
			update_me = get_entity_by_id(allow_special_ids(update['id']))
			if update_me == None:
				client.send("ERR", {'text': 'Can\'t update %s' % update['id']})
				return
			if update_me.owner_id != client.db_id and not client.has_permission(update_me, permission['modify_properties'], False):
				# If you don't have permission for modify_properties you may still be able to do the update if you're only changing specific properties
				appearance_change_props = {'id', 'name', 'desc', 'pic', 'tags'}

				if any(key not in appearance_change_props for key in update) or not client.has_permission(update_me, permission['modify_appearance'], False):
					client.send("ERR", {'text': 'You don\'t have permission to update %s' % update['id']})
					return

			if 'data' in update:
				bad = data_disallowed_for_entity_type(update_me.entity_type, update['data'])
				if bad != None:
					client.send("ERR", {'text': bad})
					del update['data']
				else:
					update_me.data = update['data']

			if 'owner_id' in update:
				if update_me.owner_id != client.db_id:
					client.send("ERR", {'text': 'Can only reassign ownership on entities you own'})
					del update['owner_id']
				update_me.owner_id = update['owner_id']

			if 'owner_username' in update:
				if update_me.owner_id != client.db_id:
					client.send("ERR", {'text': 'Can only reassign ownership on entities you own'})
					del update['owner_username']
				new_owner = find_db_id_by_username(update['owner_username'])
				if new_owner:
					update_me.owner_id = update['owner']
				else:
					client.send("ERR", {'text': 'Username \"%s\" not found' % update['owner_username']})
					del update['owner_username']

			if 'folder' in update:
				if client.has_permission(update['folder'], (permission['entry']), False) \
				and client.has_permission(update['folder'], (permission['object_entry'], permission['persistent_object_entry']), False):
					if not update_me.switch_map(update['folder']):
						client.send("ERR", {'text': 'Entity doesn\'t have permission to move there'})
						del update['folder']
				else:
					client.send("ERR", {'text': 'Don\'t have permission to move entity there'})
					del update['folder']

			if 'home' in update:
				if update['home'] == True and client.has_permission(update_me.map_id, permission['persistent_object_entry'], False):
					update_me.home_id = update_me.map_id
					update_me.home_position = [update_me.x, update_me.y]
				elif update['home'] == None:
					update_me.home_id = None
					update_me.home_position = None
				elif client.has_permission(update['home'], permission['persistent_object_entry'], False):
					update_me.home_id = update['home']
					update_me.home_position = None
				else:
					client.send("ERR", {'text': 'Don\'t have permission to set entity\'s home there'})
					del update['home']

			if 'home_position' in update and len(update['home_position']) == 2:
				update_me.home_position = update['home_position']
			if 'name' in update:
				update_me.name = update['name']
			if 'desc' in update:
				update_me.desc = update['desc']
			if 'pic' in update:
				if pic_is_okay(update['pic']):
					update_me.pic = update['pic']
				else:
					client.send("ERR", {'text': 'Invalid picture: %s' % update_me.pic})
					del update['pic']
			if 'tags' in update:
				update_me.tags = update['tags']
			if 'allow' in update:
				update_me.allow = bitfield_from_permission_list(update['allow'])
			if 'deny' in update:
				update_me.deny = bitfield_from_permission_list(update['deny'])
			if 'guest_deny' in update:
				update_me.guest_deny = bitfield_from_permission_list(update['guest_deny'])

			if not update_me.temporary:
				update_me.save()
			update_me.broadcast_who()

			# send back confirmation
			client.send("BAG", {'update': update})

		elif "move" in arg:
			move = arg['move']
			move_me = get_entity_by_id(move['id'])
			if client.has_permission(move['folder'], (permission['object_entry'], permission['persistent_object_entry']), False):
				if 'pos' in move:
					if client.has_permission(move_entity, permission['move_new_map'], False):
						move_me.switch_map(move['folder'], new_pos=move['pos'])
						client.send('BAG', {'move': move})
					else:
						client.send("ERR", {'text': 'Don\'t have permission to move entity'})
				else:
					if client.has_permission(move_entity, (permission['move'], permission['move_new_map']), False):
						move_me.switch_map(move['folder'])
						client.send('BAG', {'move': move})
					else:
						client.send("ERR", {'text': 'Don\'t have permission to move entity'})
			else:
				client.send("ERR", {'text': 'Don\'t have permission to move entity there'})

		elif "kick" in arg:
			kick = arg['kick']
			kick_me = get_entity_by_id(kick['id'])
			if kick.map_id == client.db_id or client.has_permission(kick.map_id, (permission['admin'], permission['sandbox']), False):
				kick.send_home()
				client.send("BAG", {'kick': kick})

		elif "delete" in arg:
			delete = arg['delete']

			delete_me = get_entity_by_id(delete['id'])
			if delete_me == None or delete_me.is_client():
				client.send("ERR", {'text': 'Can\'t delete %s' % delete['id']})
				return
			if delete_me.owner_id != client.db_id:
				client.send("ERR", {'text': 'You don\'t have permission to delete %s' % delete['id']})
				return

			# Move everything inside to the parent
			for c in delete_me.contents.copy():
				delete_me.remove_from_contents(c)
				delete_me.map.add_to_contents(c)

			# Delete from the database too
			if delete_me.db_id:
				c.execute('DELETE FROM Entity WHERE owner_id=? AND id=?', (client.db_id, delete['id']))
			if delete_me.map:
				delete_me.map.remove_from_contents(delete_me)
			client.send("BAG", {'remove': {'id': delete['id']}})

		elif "info" in arg:
			info = arg['info']
			info_me = get_entity_by_id(info['id'])
			if info_me == None:
				client.send("ERR", {'text': 'Can\'t get info for %s' % info['id']})
				return

			bag_info = info_me.bag_info()
			if info_me.is_client(): # No spying
				del bag_info['folder']
			client.send("BAG", {'info': bag_info})

	else:
		client.send("ERR", {'text': 'Guests don\'t have an inventory currently. Use [tt]/register username password[/tt]'})

@protocol_command()
def fn_EML(map, client, arg):
	if client.db_id != None:
		c = Database.cursor()
		if "send" in arg:
			# todo: definitely needs some limits in place to prevent abuse!

			# get a list of all the people to mail
			recipient_id = set(find_db_id_by_username(x) for x in arg['send']['to'])
			recipient_string = ','.join([str(x) for x in recipient_id])

			if any(x == None for x in recipient_id):
				client.send("ERR", {'text': 'Couldn\'t find one or more users you wanted to mail'})
				return

			# let the client know who sent it, since the 'send' argument will get passed along directly
			arg['send']['from'] = client.username

			# send everyone their mail
			for id in recipient_id:
				if id == None:
					continue
				c.execute("INSERT INTO Mail (owner_id, sender_id, recipients, subject, contents, created_at, flags) VALUES (?, ?, ?, ?, ?, ?, ?)", (id, client.db_id, recipient_string, arg['send']['subject'], arg['send']['contents'], datetime.datetime.now(), 0))

				# is that person online? tell them!
				find = find_client_by_db_id(id)
				if find:
					arg['send']['id'] = c.execute('SELECT last_insert_rowid()').fetchone()[0]
					find.send("EML", {'receive': arg['send']})

			client.send("EML", {'sent': {'subject': arg['send']['subject']}}) #acknowledge
			client.send("MSG", {'text': 'Sent mail to %d users' % len(recipient_id)})

		elif "read" in arg:
			c.execute('UPDATE Mail SET flags=1 WHERE owner_id=? AND id=?', (client.db_id, arg['read']))
		elif "delete" in arg:
			c.execute('DELETE FROM Mail WHERE owner_id=? AND id=?', (client.db_id, arg['delete']))

	else:
		client.send("ERR", {'text': 'Guests don\'t have mail. Use [tt]/register username password[/tt]'})

@protocol_command()
def fn_MSG(map, client, arg):
	if map:
		text = arg["text"]
		map.broadcast("MSG", {'name': client.name, 'username': client.username_or_id(), 'text': escape_tags(text)}, remote_category=botwatch_type['chat'])

@protocol_command()
def fn_TSD(map, client, arg):
	c = Database.cursor()
	c.execute('SELECT data FROM Entity WHERE type=? AND id=?', (entity_type('tileset'), arg['id'],))
	result = c.fetchone()
	if result == None:
		client.send("ERR", {'text': 'Invalid item ID'})
	else:
		client.send("TSD", {'id': arg['id'], 'data': result[0]})

@protocol_command()
def fn_IMG(map, client, arg):
	c = Database.cursor()
	c.execute('SELECT data FROM Entity WHERE type=? AND id=?', (entity_type['image'], arg['id'],))
	result = c.fetchone()
	if result == None:
		client.send("ERR", {'text': 'Invalid item ID'})
	else:
		client.send("IMG", {'id': arg['id'], 'url': loads_if_not_none(result[0])})

@protocol_command(map_only=True)
def fn_MAI(map, client, arg):
	send_all_info = must_be_map_owner(client, True, give_error=False)
	client.send("MAI", map.map_info(all_info=send_all_info))

@protocol_command(map_only=True)
def fn_DEL(map, client, arg):
	x1 = arg["pos"][0]
	y1 = arg["pos"][1]
	x2 = arg["pos"][2]
	y2 = arg["pos"][3]
	if client.has_permission(map, permission['build'], True) or must_be_map_owner(client, True, give_error=False):
		if not map.map_data_loaded:
			client.send("ERR", {'text': 'Map isn\'t loaded, so it can\'t be modified'})
			return
		map.map_data_modified = True

		for x in range(x1, x2+1):
			for y in range(y1, y2+1):
				if arg["turf"]:
					map.turfs[x][y] = None;
				if arg["obj"]:
					map.objs[x][y] = None;
		map.broadcast("MAP", map.map_section(x1, y1, x2, y2))

		# make username available to listeners
		arg['username'] = client.username_or_id()
		map.broadcast("DEL", arg, remote_only=True, remote_category=botwatch_type['build'])
	else:
		client.send("MAP", map.map_section(x1, y1, x2, y2))
		client.send("ERR", {'text': 'Building is disabled on this map'})

@protocol_command(map_only=True)
def fn_PUT(map, client, arg):
	def notify_listeners():
		# make username available to listeners
		arg['username'] = client.username_or_id()
		map.broadcast("PUT", arg, remote_only=True, remote_category=botwatch_type['build'])

	x = arg["pos"][0]
	y = arg["pos"][1]
	if client.has_permission(map, permission['build'], True) or must_be_map_owner(client, True, give_error=False):
		if not map.map_data_loaded:
			client.send("ERR", {'text': 'Map isn\'t loaded, so it can\'t be modified'})
			return
		map.map_data_modified = True

		# verify the the tiles you're attempting to put down are actually good
		if arg["obj"]: #object
			tile_test = [tile_is_okay(x) for x in arg["atom"]]
			if all(x[0] for x in tile_test): # all tiles pass the test
				map.objs[x][y] = arg["atom"]
				map.broadcast("MAP", map.map_section(x, y, x, y))
				notify_listeners()
			else:
				# todo: give a reason?
				client.send("MAP", map.map_section(x, y, x, y))
				client.send("ERR", {'text': 'Placed objects rejected'})
		else: #turf
			tile_test = tile_is_okay(arg["atom"])
			if tile_test[0]:
				map.turfs[x][y] = arg["atom"]
				map.broadcast("MAP", map.map_section(x, y, x, y))
				notify_listeners()
			else:
				client.send("MAP", map.map_section(x, y, x, y))
				client.send("ERR", {'text': 'Tile [tt]%s[/tt] rejected (%s)' % (arg["atom"], tile_test[1])})
	else:
		client.send("MAP", map.map_section(x, y, x, y))
		client.send("ERR", {'text': 'Building is disabled on this map'})

@protocol_command(map_only=True)
def fn_BLK(map, client, arg):
	if client.has_permission(map, permission['bulk_build'], False) or must_be_map_owner(client, True, give_error=False):
		if not map.map_data_loaded:
			client.send("ERR", {'text': 'Map isn\'t loaded, so it can\'t be modified'})
			return
		map.map_data_modified = True

		# verify the tiles
		for turf in arg["turf"]:
			if not tile_is_okay(turf[2])[0]:
				client.send("ERR", {'text': 'Bad turf in bulk build'})
				return
		for obj in arg["obj"]:
			tile_test = [tile_is_okay(x) for x in obj[2]]
			if any(not x[0] for x in tile_test): # any tiles don't pass the test
				client.send("ERR", {'text': 'Bad obj in bulk build'})
				return
		# make username available to other clients
		arg['username'] = client.username_or_id()

		# do copies
		for copy in arg["copy"]:
			do_turf = ("turf" not in copy) or copy["turf"]
			do_obj = ("obj" not in copy) or copy["obj"]
			x1, y1, width, height = copy["src"]
			x2, y2                = copy["dst"]

			# turf
			if do_turf:
				copied = []
				for w in range(width):
					row = []
					for h in range(height):
						row.append(map.turfs[x1+w][y1+h])
					copied.append(row)

				for w in range(width):
					for h in range(height):
						map.turfs[x2+w][y2+h] = copied[w][h]
			# obj
			if do_obj:
				copied = []
				for w in range(width):
					row = []
					for h in range(height):
						row.append(map.objs[x1+w][y1+h])
					copied.append(row)

				for w in range(width):
					for h in range(height):
						map.objs[x2+w][y2+h] = copied[w][h]

		# place the tiles
		for turf in arg["turf"]:
			x = turf[0]
			y = turf[1]
			a = turf[2]
			width = 1
			height = 1
			if len(turf) == 5:
				width = turf[3]
				height = turf[4]
			for w in range(0, width):
				for h in range(0, height):
					map.turfs[x+w][y+h] = a
		# place the object lists
		for obj in arg["obj"]:
			x = obj[0]
			y = obj[1]
			a = obj[2]
			width = 1
			height = 1
			if len(turf) == 5:
				width = turf[3]
				height = turf[4]
			for w in range(0, width):
				for h in range(0, height):
					map.objs[x+w][y+h] = a
		map.broadcast("BLK", arg, remote_category=botwatch_type['build'])
	else:
		client.send("ERR", {'text': 'Bulk building is disabled on this map'})

@protocol_command()
def fn_WHO(map, client, arg):
	if arg["update"]:
		valid_data = validate_client_who(client.protocol_id(), arg["update"])
		for key,value in valid_data.items():
			if key != 'id':
				setattr(client,key,value)
		map.broadcast("WHO", {"update": valid_data})
	else:
		client.send("ERR", {'text': 'not implemented'})

@protocol_command()
def fn_VER(map, client, arg):
	# Receives version info from the client, but ignore it for now
	server_software_name = "Tilemap Town server"
	server_software_version = "0.2.0"
	server_software_code = "https://github.com/NovaSquirrel/TilemapTown"

	client.send("VER", {'name': server_software_name, 'version': server_software_version, 'code': server_software_code})

# -------------------------------------

def handle_protocol_command(map, client, command, arg):
	# Attempt to run the command handler if it exists
	if command in handlers:
		if command in map_only_commands and (client.map == None or not client.map.is_map()):
			client.send("ERR", {'text': 'Protocol command must be done on a map: %s' % command})
		else:
			return handlers[command](map, client, arg)
	else:
		client.send("ERR", {'text': 'Bad protocol command: %s' % command})
