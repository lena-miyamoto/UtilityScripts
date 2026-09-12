#!/usr/bin/python3
import re
import os.path
import urllib.request
import urllib.parse
from csvreader import CsvReader

class WikicommonsResource:
	@staticmethod
	def get_imageurl(generic_identifier):
		response = None

		try:
			url = 'http://commons.wikimedia.org/wiki/File:' + generic_identifier
			response = urllib.request.urlopen(url)
			html = str(response.read())
		except urllib.error.HTTPError as e:
			pass
			#print ("[!] Error code: ",  e.code)
		except urllib.error.URLError as e:
			pass
			#print ("[!] Reason: ",  e.reason)
		#end try
	
		if response != None and response.getcode() == 200:
			match = re.search(r'<div class="fullMedia"><a href="([^"]+)', str(html))
			image_url = match.group(1)
		
			return 'http:' + image_url if image_url.startswith('//') else image_url
		#end if
	
		return None
	#end def
	
	@staticmethod
	def save_url(url, path):
		response = None

		try:
			response = urllib.request.urlopen(url)

			with open(path, 'wb') as f:
				f.write(response.read())
			#end with
		except urllib.error.HTTPError as e:
			print ("[!] Error code: ",  e.code)
		except urllib.error.URLError as e:
			print ("[!] Reason: ",  e.reason)
		#end try
	#end def
	
	def __init__(self, target_dir):
		self.target_dir = target_dir
		
		if not os.path.exists(target_dir):
			os.makedirs(target_dir)
		#end if
	#end def
	
	def _save_image(self, image_url):
		filename = urllib.parse.unquote(image_url[image_url.rfind('/') + 1:])
		save_path = self.target_dir + '/' + filename
	
		print('Downloading ' + image_url + ' to ' + save_path + ' ...')
		if os.path.exists(save_path):
			print('File ' + save_path + ' already exists.')
		else:
			WikicommonsResource.save_url(image_url, save_path)
		#end if
	#end def
#end class

class CharacterResource(WikicommonsResource):
	def __init__(self, target_dir, imgtype, filetype):
		super(CharacterResource, self).__init__(target_dir)
		
		self.imgtype  = imgtype
		self.filetype = filetype
	#end def
#end def

class HiraganaResource(CharacterResource):	
	@staticmethod
	def get_hiraganas():
		for code in range(12354, 12435):
			yield chr(code)
		#end for 
	#def
	
	def __init__(self, target_dir, imgtype, filetype):
		super(HiraganaResource, self).__init__(target_dir, imgtype, filetype)
	#end def
	
	def fetch_hiraganas(self, hiraganas):
		for hiragana in hiraganas:
			self.fetch_hiragana(hiragana)
		#end def
	#end def
	
	def fetch_hiragana(self, hiragana):
		encoded_char = urllib.parse.quote(hiragana)
		image_url = WikicommonsResource.get_imageurl('Hiragana_' + encoded_char + '_' + self.imgtype + '.' + self.filetype)
	
		if image_url != None:
			self._save_image(image_url)
		#end if
	#end def
#end class

class KatakanaResource(CharacterResource):	
	@staticmethod
	def get_katakanas():
		for code in range(12449, 12531):
			yield chr(code)
		#end for 
	#def
	
	def __init__(self, target_dir, imgtype, filetype):
		super(KatakanaResource, self).__init__(target_dir, imgtype, filetype)
	#end def
	
	def fetch_katakanas(self, katakanas):
		for katakana in katakanas:
			self.fetch_katakana(katakana)
		#end def
	#end def
	
	def fetch_katakana(self, katakana):
		encoded_char = urllib.parse.quote(katakana)
		image_url = WikicommonsResource.get_imageurl('Katakana_' + encoded_char + '_' + self.imgtype + '.' + self.filetype)
		
		if image_url != None:
			self._save_image(image_url)
		#end if
	#end def
#end class

class KanjiResource(CharacterResource):
	def __init__(self, target_dir, imgtype, filetype):
		super(KanjiResource, self).__init__(target_dir, imgtype, filetype)
	#end def
	
	def fetch_kanjis(self, kanjis):
		for kanji in kanjis:
			self.fetch_kanji(kanji)
		#end def
	#end def
	
	def fetch_kanji(self, kanji):
		encoded_char = urllib.parse.quote(kanji)
		image_url = WikicommonsResource.get_imageurl(encoded_char + '-j' + self.imgtype + '.' + self.filetype) # check for japan-specific file
	
		if image_url != None:
			print('Found Japan-specific image for kanji ' + kanji + '!')
			self._save_image(image_url)
		else:
			image_url = WikicommonsResource.get_imageurl(encoded_char + '-' + self.imgtype + '.' + self.filetype)
		
			if image_url != None:
				self._save_image(image_url)
			else:
				print('Cannot download image for kanji ' + kanji)
			#end if
		#end if
	#end def
#end class

hiraganas = HiraganaResource(os.path.expanduser('~/Documents/hiragana_animated/'), 'stroke_order_animation', 'gif')
katakanas = KatakanaResource(os.path.expanduser('~/Documents/katakana_animated/'), 'stroke_order_animation', 'gif')
kanjis    = KanjiResource(os.path.expanduser('~/Documents/kanji_red/'), 'red', 'png') # 'order', 'red'

#hiraganas.fetch_hiraganas(HiraganaResource.get_hiraganas())
#katakanas.fetch_katakanas(KatakanaResource.get_katakanas())
kanjilist = CsvReader(',', '"')
kanjis.fetch_kanjis([row[0] for row in kanjilist.parse('csv/kanji80.csv')])
