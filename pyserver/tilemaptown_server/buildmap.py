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

import json, asyncio, random, datetime
from .buildglobal import *
from .buildentity import *

# Unused currently
DirX = [ 1,  1,  0, -1, -1, -1,  0,  1]
DirY = [ 0,  1,  1,  1,  0, -1, -1, -1]

class Map(Entity):
	def __init__(self,width=100,height=100,id=None,creator_id=None):
		super().__init__(entity_type['map'], creator_id = creator_id)

		# map stuff
		self.default_turf = "grass"
		self.start_pos = [5, 5]
		self.name = "Map"
		self.id = 0
		self.map_flags = 0
 
		# map scripting
		self.has_script = False
		#loop = asyncio.get_event_loop()
		#self.script_queue = asyncio.Queue(loop=loop)

		if id == None:
			self.blank_map(width, height)
		elif not self.load(id):
			self.db_id = None

	def __del__(self):
		self.cleanup()
		super().__del__()

	def clean_up(self):
		""" Clean up everything before a map unload """
		super().cleanup()

	def blank_map(self, width, height):
		""" Make a blank map of a given size """
		self.width = width
		self.height = height

		# construct the map
		self.turfs = []
		self.objs = []
		for x in range(0, width):
			self.turfs.append([None] * height)
			self.objs.append([None] * height)

	def load(self, map_id):
		""" Load a map from a file """
		c = Database.cursor()
		c.execute('SELECT flags, start_x, start_y, width, height, default_turf FROM Map WHERE entity_id=?', (map_id,))
		result = c.fetchone()
		if result == None:
			return False

		self.id = map_id
		self.map_flags = result[0]
		self.start_pos = [result[1], result[2]]
		self.width = result[3]  # Will be overwritten by the blank_map call but that's ok
		self.height = result[4]
		self.default_turf = result[5]

		entity_loaded = super().load(map_id)
		if entity_loaded:
			# Parse map data
			if self.data:
				s = json.loads(self.data)
				self.blank_map(s["pos"][2]+1, s["pos"][3]+1) # [firstX, firstY, lastX, lastY]
				for t in s["turf"]:
					self.turfs[t[0]][t[1]] = t[2]
				for o in s["obj"]:
					self.objs[o[0]][o[1]] = o[2]
			else:
				self.blank_map(self.width, self.height)
		else:
			return False

		return super().load(map_id)

	def save(self):
		""" Save the map to the database """
		super().save()
		if self.db_id == None:
			return

		# Create new map if map doesn't already exist
		c = Database.cursor()
		c.execute('SELECT entity_id FROM Map WHERE entity_id=?', (self.db_id,))
		if c.fetchone() == None:
			c.execute("INSERT INTO Map (entity_id) VALUES (?)", (self.db_id,))
			self.db_id = c.lastrowid
			if self.db_id == None:
				return

		# Update the map
		values = (self.map_flags, self.start_pos[0], self.start_pos[1], self.width, self.height, self.default_turf, self.db_id)
		c.execute("UPDATE Map SET flags=?, start_x=?, start_y=?, width=?, height=?, default_turf=? WHERE entity_id=?", values)

	def map_section(self, x1, y1, x2, y2):
		""" Returns a section of map as a list of turfs and objects """
		# clamp down the numbers
		x1 = min(self.width, max(0, x1))
		y1 = min(self.height, max(0, y1))
		x2 = min(self.width, max(0, x2))
		y2 = min(self.height, max(0, y2))

		# scan the map
		turfs = []
		objs  = []
		for x in range(x1, x2+1):
			for y in range(y1, y2+1):
				if self.turfs[x][y] != None:
					turfs.append([x, y, self.turfs[x][y]])
				if self.objs[x][y] != None:
					objs.append([x, y, self.objs[x][y]])
		return {'pos': [x1, y1, x2, y2], 'default': self.default_turf, 'turf': turfs, 'obj': objs}

	def map_info(self, all_info=False):
		""" MAI message data """
		out = {'name': self.name, 'id': self.id, 'owner': find_username_by_db_id(self.owner_id) or '?', 'default': self.default_turf, 'size': [self.width, self.height], 'public': self.map_flags & mapflag['public'] != 0, 'private': self.deny & permission['entry'] != 0, 'build_enabled': self.allow & permission['build'] != 0, 'full_sandbox': self.allow & permission['sandbox'] != 0}
		if all_info:
			out['start_pos'] = self.start_pos
		return out

	def is_map(self):
		return True
