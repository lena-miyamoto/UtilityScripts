#!/usr/bin/env python3

# Each category below is a list of regular expressions. Patterns are matched
# case-insensitively against the merchant with re.search (anywhere in the
# string). Use '^' to anchor to the start, '$' for the end, and '.*' for a
# wildcard run.

groceries = [
  r'782 AVIA SB',
  r'782 AVIA STEG IN',
  r'ACTION 3354',
  r'ANKERBROT',
  r'BACKEREI FILIPP GMBH',
  r'BIERTEMPEL LINZ',
  r'BILLA DANKT',
  r'BIPA DANKT',
  r'DENIZLEBENSMITTELHANDE',
  r'DM-FIL\.',
  r'EDEKA MAIER',
  r'GO ASIA SUPERMARKT',
  r'HOFER DANKT',
  r'HONEDER NATURBACKSTU',
  r'HONGKONG SHOP',
  r'JET 5118',
  r'MUELLER PASSAU',
  r'OMV',
  r'REFORM MARTIN LINZ',
  r'RESCH & FRISCH-EINZELH',
  r'ROSSMANN 3678',
  r'SPAR DANKT',
  r'SPAR FIL\.',
  r'TEA & TEE COMPANY',
  r'TURMOEL 99',
  r'TURMOL 99',
  r'YORMAS AG',
]

restaurants = [
  r'220GRAD RUPERTINUM',
  r'ASIA COCONUT',
  r'BACH KG',
  r'BACKSHOP INNSTADT',
  r'BADESCHIFF WIEN',
  r'BAR SOLARIS',
  r'BELLEVUE BAR RESTAURAN',
  r'BLOCHBERGEREISPRODUKTG',
  r'BRAURESTAURANT IMLAUER',
  r'CASA MEXICO',
  r'CAFE SKYGARDEN',
  r'CAFE STERN',
  r'CAFE TRAXLMAYR',
  r'CHANDNI INDISCHES REST',
  r'CHAY-TEE',
  r'CHINARESTAURANT SIEGRE',
  r'COCONUT THAI-RESTAURAN',
  r'DON ASIA IMBISS',
  r'DORNACHER STUBN',
  r'EL PASO',
  r'EXXTRABLATT GASTROGMBH',
  r'GAME AND DINE',
  r'GN ANTICA LOCANDA',
  r'GOLDENE PAGODE',
  r'GRUNE PAPAYA',
  r'IGNAZ UND ROSALIA MARK',
  r'INNSENTO HEALTH CAMPUS',
  r'INNSENTO HEALTH CAPMU',
  r'KIRCHENWIRT',
  r'KOJIRO',
  r'KULINARIO EAT\.ENJOY\.EX',
  r'KULINARIO EAT\.ENJOY\.EXNYA\*ALOIS DALLMAYR AUT',
  "L'OSTERIA",
  r'LA RIVA',
  r'LE CROBAG',
  r'LEBERKAS-PEPI',
  r'LILY KITCHEN',
  r'MAI THAI WOK & GRILL',
  "MANGO'S BAR",
  r'MCDONALD',
  r'MIYAKO RAMEN RESTAURAN',
  r'MONASTERO',
  r'MONTE VERDE',
  r'MR BOXTEA BUBBLETEAS',
  r'MUSIKCAFE SAX',
  r'NEW NAMASTEY INDIA',
  r'NYA\*ALOIS DALLMAYR AUT',
  r'NYX\*ANKERSNACKCOFFEEGM',
  r'OCEAN PARK PLUSCITY',
  r'PANDA WOK CHINA RESTAU',
  r'PATTAYA THAI RESTAURAN',
  r'REST GOSCINNA',
  r'RESTAURANT ATHENE',
  r'RESTAURANT AYAM ZAMAN',
  r'RESTAURANT BLAAS',
  "RESTAURANT BO'S",
  r'RESTAURANT BOS',
  r'RESTAURANT HOFKNEIPE',
  r'RESTAURANT ORPHEUS',
  r'RESTAURANT OST18',
  r'RISTORANTE LA TORRE',
  r'ROSMARINO',
  r'SCHACHERMAYER LINZ',
  r'SCHLOSSCAFE-LINZ',
  r'SHANGSUSHI UND GRILL',
  r'SICHUAN IMPRESSION',
  r'STARBUCKS 82884 PASSAU',
  r'STEFAN STUBM',
  r'SUMON',
  r'SUMUP  \*BRB',
  r'SUMUP  \*CHINAPALAST',
  r'SUMUP  \*HOAI ANH COCOS',
  r'SUMUP  \*LECKEROLLS',
  r'SUMUP  \*ROSMARINO',
  r'TEESALON MADAME WU',
  r'VEVI',
  r'WALKERCAFE BAR CLUB',
  r'WEINSTADL',
  r'WOK UND SUSHI',
  r'WU GMBH',
  r'YOMIA GMBH',
  r'ZOO BUFFET',
  r'ZUR LIESL',
  r'AROMA INDISCHES RESTAU',
  r'EBISU SUSHI',
  r'ESPRESSO HOUSE GERMANY',
  r'FRONT FOOD',
  r'GELATERIA LA ROMANA',
  r'SANTOOR RESTAURANT',
  r'STEFAN STUBN',
  r'SUMUP  \*SCHOKOLADENPAR',
  r'SURACE EISSALON LENTIA',
  r'SWING KITCHEN 006',
  r'TOMOCHAN RAMEN',
  r'ZINAS EATERY',
]

medical = [
  r'DR ADRIAN MIRTL',
  r'DR EVELYN DURNIG',
  r'DR\. EVELYN DURNIG',
  r'FIELMANN',
  r'HEINDL IHR BANDAGIST',
  r'IMPFSERVICE, NRH 1\.STO',
  r'KLINIK JESUITENSCHLOES',
  r'MIRIAM M MOTTL',
  r'OOEGKK GESUNDHEITSZENT',
  r'ORDINATION DR\. KOHLER',
  r'PARACELSUS-APOTHEK',
  r'SONNENSTUDIO MEGA SUN',
  r'ST\. MAGDALENA APOTHEKE',
  r'SUMUP  \*MEDPULSLINZ',
  r'VERA PISCHULTI',
  r'WITTELSBACHER APOTHEKE',
  r'APOTHEKE',
]

dynatrace_lunch = [
  r'GMS GOURMET DYNATRACE',
  r'GMS GOURMET-DYNATRACE',
  r'MENSA LINZ',
]

misc = [
  r'B7 FAHRRADZENTRUM',
  r'CHOCOTEGA',
  r'DAS FASSL VON PASSAU',
  r'DAS FLAEMISCHE SCHOKOL',
  r'DOUGLAS 44',
  r'FITINN LINZ RAINERSTRA',
  r'HARTLAUER FIL\.',
  r'HOLLYWOOD MEGAPLEX',
  r'IKEA WIEN NORD',
  r'INTERSPORT POTSCHER',
  r'INTERSPORT WINNINGER',
  r'JYSK LINZ AT518',
  r'LIBRO FIL\.',
  r'MOVIEMENTO',
  r'MUSIKINSTRUMENTE DANNE',
  r'NYX\*DONBOARDSERVICEGMB',
  r'OBI BAU- UND HEIMWERKE',
  r'OBI SAGT DANKE',
  r'PARFUEMERIE DOUGLAS',
  r'POST 4046',
  r'REISEPASS CENTER NEUES',
  r'TABAK-TRAFIK GROBNER',
  r'TABAK-TRAFIK HEIDARZAD',
  r'TABAK-TRAFIK MAYER',
  r'THALIA\.AT FIL\.',
  r'XXXLUTZ LINZ',
  r'ZAHLSTELLE FUHRERSCHEI',
  r'ZOO LINZ',
]

uncategorized = [
  r'FIND TEA',
  r'LA PROFESAR',
  r'MONKEYS SAGT DANKE',
  r'SUMUP  \*ASCHAUER',
  r'SUMUP  \*BEATRIX KOSIK',
  r'SUMUP  \*FEST \+ GAST',
  r'SUMUP  \*LEONHARTSBERGE',
  r'SUMUP  \*PRTN KG',
]

public_transport = [
  r'ONE MOBILITY TICKETING GMBH',
  r'OBB TICKET',
]

dues_and_fees = [
  r'ORF-BEITRAGS SERVICE GMBH',
  r'LIWEST KABELMEDIEN GMBH',
  r'HOT TELEKOM UND SERVICE GMBH',
  r'GWG - Gemeinn\. Wohnungsges\. der Stadt Linz GmbH',
]

clothing = [
  r'ULLA POPKEN LINZ',
  r'VOLKSHILFE',
]

services = [
  r'KLIPP FRISOER GMBH',
]

online_shopping = [
  r'AMAZON MKTPL\*',
  r'AMAZON\.DE\*',
  r'AMAZON PRIM\*',
  r'AMAZON\*',
  r'AMZN MKTP DE\*',
  r'WWW\.AMAZON\.\*',
  r'PRIME VIDEO SHOP AMZN\.DE',
  r'ZALANDO PAYMENTS BERLIN',
  r'ZALANDO PAYMENTS GMBH BERLIN',
  r'WILLHABEN',
]

steam = [
  r'STEAM PURCHASE SEATTLE',
  r'STEAMGAMES\.COM',
]

spotify = [
  r'Spotify',
]

paypal = [
  r'PAYPAL',
]

# Category key -> pattern list. Used by parse-kontoauszug.py to compile
# patterns and by --print-categories to regenerate this file.
PATTERNS = {
  'groceries': groceries,
  'restaurants': restaurants,
  'medical': medical,
  'dynatrace_lunch': dynatrace_lunch,
  'misc': misc,
  'uncategorized': uncategorized,
  'public_transport': public_transport,
  'dues_and_fees': dues_and_fees,
  'clothing': clothing,
  'services': services,
  'online_shopping': online_shopping,
  'steam': steam,
  'spotify': spotify,
  'paypal': paypal,
}

# Ordered category sets per source. First matching pattern wins.
giro_categories = [
  ('groceries', 'Groceries'),
  ('restaurants', 'Restaurants'),
  ('medical', 'Medical'),
  ('dynatrace_lunch', 'Dynatrace Lunch'),
  ('misc', 'Misc'),
  ('clothing', 'Clothing'),
  ('services', 'Services'),
  ('online_shopping', 'Online Shopping'),
  ('public_transport', 'Public Transport'),
  ('dues_and_fees', 'Dues and Fees'),
  ('uncategorized', 'Uncategorized'),
]

creditcard_categories = [
  ('online_shopping', 'Online Shopping'),
  ('steam', 'Steam'),
  ('spotify', 'Spotify'),
  ('paypal', 'PayPal'),
]

# Fallback category used when no pattern matches.
FALLBACK = ('new', 'New')
