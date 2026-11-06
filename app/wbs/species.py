"""Starting species list: feeder birds of the Ottawa area (eastern Ontario), plus non-bird classes.

Edit the list in the web UI (Species page); this only seeds an empty database.
"""

NON_BIRD = [
    ("Empty", "", "No animal visible (wind, light change, bird already gone)."),
    ("Squirrel", "Sciuridae", "Any squirrel."),
    ("Chipmunk", "Tamias striatus", ""),
    ("Other animal", "", "Raccoon, cat, insect, ..."),
    ("Unknown bird", "Aves", "A bird is visible but can't be identified (blurry, cut off)."),
]

BIRDS = [
    ("Black-capped Chickadee", "Poecile atricapillus"),
    ("Blue Jay", "Cyanocitta cristata"),
    ("Northern Cardinal", "Cardinalis cardinalis"),
    ("American Goldfinch", "Spinus tristis"),
    ("House Finch", "Haemorhous mexicanus"),
    ("Purple Finch", "Haemorhous purpureus"),
    ("House Sparrow", "Passer domesticus"),
    ("American Tree Sparrow", "Spizelloides arborea"),
    ("Song Sparrow", "Melospiza melodia"),
    ("Chipping Sparrow", "Spizella passerina"),
    ("White-throated Sparrow", "Zonotrichia albicollis"),
    ("White-crowned Sparrow", "Zonotrichia leucophrys"),
    ("Dark-eyed Junco", "Junco hyemalis"),
    ("White-breasted Nuthatch", "Sitta carolinensis"),
    ("Red-breasted Nuthatch", "Sitta canadensis"),
    ("Downy Woodpecker", "Dryobates pubescens"),
    ("Hairy Woodpecker", "Dryobates villosus"),
    ("Red-bellied Woodpecker", "Melanerpes carolinus"),
    ("Northern Flicker", "Colaptes auratus"),
    ("Pileated Woodpecker", "Dryocopus pileatus"),
    ("Mourning Dove", "Zenaida macroura"),
    ("Rock Pigeon", "Columba livia"),
    ("European Starling", "Sturnus vulgaris"),
    ("Common Grackle", "Quiscalus quiscula"),
    ("Red-winged Blackbird", "Agelaius phoeniceus"),
    ("Brown-headed Cowbird", "Molothrus ater"),
    ("American Crow", "Corvus brachyrhynchos"),
    ("American Robin", "Turdus migratorius"),
    ("Tufted Titmouse", "Baeolophus bicolor"),
    ("Pine Siskin", "Spinus pinus"),
    ("Common Redpoll", "Acanthis flammea"),
    ("Evening Grosbeak", "Coccothraustes vespertinus"),
    ("Rose-breasted Grosbeak", "Pheucticus ludovicianus"),
    ("Indigo Bunting", "Passerina cyanea"),
    ("Baltimore Oriole", "Icterus galbula"),
    ("Gray Catbird", "Dumetella carolinensis"),
    ("Cedar Waxwing", "Bombycilla cedrorum"),
    ("Ruby-throated Hummingbird", "Archilochus colubris"),
    ("Eastern Towhee", "Pipilo erythrophthalmus"),
    ("Fox Sparrow", "Passerella iliaca"),
    ("Brown Creeper", "Certhia americana"),
    ("Carolina Wren", "Thryothorus ludovicianus"),
    ("Yellow-rumped Warbler", "Setophaga coronata"),
    ("Snow Bunting", "Plectrophenax nivalis"),
    ("Pine Grosbeak", "Pinicola enucleator"),
    ("Sharp-shinned Hawk", "Accipiter striatus"),
    ("Cooper's Hawk", "Astur cooperii"),
    ("Wild Turkey", "Meleagris gallopavo"),
    # Ottawa-area winter visitors
    ("Bohemian Waxwing", "Bombycilla garrulus"),
    ("Northern Shrike", "Lanius borealis"),
    ("Canada Jay", "Perisoreus canadensis"),
    ("Red Crossbill", "Loxia curvirostra"),
    ("White-winged Crossbill", "Loxia leucoptera"),
    ("Hoary Redpoll", "Acanthis hornemanni"),
]


# Seasonal likelihood around Ottawa, one character per month (Jan..Dec):
#   2 = expected (resident / breeding / wintering), 1 = possible (migrating, irruptive, uncommon), 0 = very unlikely.
# Hand-made from general range knowledge (2026-11-05), NOT from sightings data; eBird's bar charts could replace it.
SEASON = {
    "Black-capped Chickadee": "222222222222", "Blue Jay": "222222222222", "Northern Cardinal": "222222222222",
    "American Goldfinch": "222222222222", "House Finch": "222222222222", "Purple Finch": "111222222211",
    "House Sparrow": "222222222222", "American Tree Sparrow": "222100000122", "Song Sparrow": "001222222210",
    "Chipping Sparrow": "000122222100", "White-throated Sparrow": "000221112210", "White-crowned Sparrow": "000120001200",
    "Dark-eyed Junco": "222210000122", "White-breasted Nuthatch": "222222222222", "Red-breasted Nuthatch": "222222222222",
    "Downy Woodpecker": "222222222222", "Hairy Woodpecker": "222222222222", "Red-bellied Woodpecker": "111111111111",
    "Northern Flicker": "001222222210", "Pileated Woodpecker": "222222222222", "Mourning Dove": "222222222222",
    "Rock Pigeon": "222222222222", "European Starling": "222222222222", "Common Grackle": "001222222100",
    "Red-winged Blackbird": "001222222100", "Brown-headed Cowbird": "001222221000", "American Crow": "222222222222",
    "American Robin": "112222222211", "Tufted Titmouse": "000000000000", "Pine Siskin": "111111111111",
    "Common Redpoll": "221000000012", "Evening Grosbeak": "111000000011", "Rose-breasted Grosbeak": "000022221000",
    "Indigo Bunting": "000012221000", "Baltimore Oriole": "000022221000", "Gray Catbird": "000022222100",
    "Cedar Waxwing": "111222222211", "Ruby-throated Hummingbird": "000022221000", "Eastern Towhee": "000111111000",
    "Fox Sparrow": "001200000210", "Brown Creeper": "111111111111", "Carolina Wren": "000000000000",
    "Yellow-rumped Warbler": "000121112200", "Snow Bunting": "110000000011", "Pine Grosbeak": "110000000011",
    "Sharp-shinned Hawk": "111111111111", "Cooper's Hawk": "111111111111", "Wild Turkey": "111111111111",
    "Bohemian Waxwing": "111000000011", "Northern Shrike": "110000000011", "Canada Jay": "000000000000",
    "Red Crossbill": "111111111111", "White-winged Crossbill": "111000000011", "Hoary Redpoll": "110000000001",
}
SEASON_WORDS = {2: "expected", 1: "possible (migrating or irregular)", 0: "very unlikely"}


def season_level(name: str, month: int) -> int | None:
    """0/1/2 for this species in month 1..12, or None if it isn't in the table (non-birds, added species)."""
    s = SEASON.get(name)
    return int(s[month - 1]) if s else None


# Bird families (scientific name -> common name) for the Dataset page.
FAMILY_NAMES = {
    "Paridae": "Chickadees and titmice", "Corvidae": "Jays and crows", "Cardinalidae": "Cardinals and grosbeaks",
    "Fringillidae": "Finches", "Passeridae": "Old World sparrows", "Passerellidae": "New World sparrows",
    "Sittidae": "Nuthatches", "Picidae": "Woodpeckers", "Columbidae": "Pigeons and doves", "Sturnidae": "Starlings",
    "Icteridae": "Blackbirds and orioles", "Turdidae": "Thrushes", "Mimidae": "Catbirds and mockingbirds",
    "Bombycillidae": "Waxwings", "Trochilidae": "Hummingbirds", "Certhiidae": "Treecreepers",
    "Troglodytidae": "Wrens", "Parulidae": "Wood-warblers", "Calcariidae": "Longspurs and snow buntings",
    "Accipitridae": "Hawks and eagles", "Phasianidae": "Turkeys and grouse", "Laniidae": "Shrikes",
    "Sciuridae": "Squirrels",
}
FAMILY = {
    "Black-capped Chickadee": "Paridae", "Tufted Titmouse": "Paridae",
    "Blue Jay": "Corvidae", "American Crow": "Corvidae", "Canada Jay": "Corvidae",
    "Northern Cardinal": "Cardinalidae", "Rose-breasted Grosbeak": "Cardinalidae", "Indigo Bunting": "Cardinalidae",
    "American Goldfinch": "Fringillidae", "House Finch": "Fringillidae", "Purple Finch": "Fringillidae",
    "Pine Siskin": "Fringillidae", "Common Redpoll": "Fringillidae", "Hoary Redpoll": "Fringillidae",
    "Evening Grosbeak": "Fringillidae", "Pine Grosbeak": "Fringillidae", "Red Crossbill": "Fringillidae",
    "White-winged Crossbill": "Fringillidae",
    "House Sparrow": "Passeridae",
    "American Tree Sparrow": "Passerellidae", "Song Sparrow": "Passerellidae", "Chipping Sparrow": "Passerellidae",
    "White-throated Sparrow": "Passerellidae", "White-crowned Sparrow": "Passerellidae", "Dark-eyed Junco": "Passerellidae",
    "Eastern Towhee": "Passerellidae", "Fox Sparrow": "Passerellidae",
    "White-breasted Nuthatch": "Sittidae", "Red-breasted Nuthatch": "Sittidae",
    "Downy Woodpecker": "Picidae", "Hairy Woodpecker": "Picidae", "Red-bellied Woodpecker": "Picidae",
    "Northern Flicker": "Picidae", "Pileated Woodpecker": "Picidae",
    "Mourning Dove": "Columbidae", "Rock Pigeon": "Columbidae",
    "European Starling": "Sturnidae",
    "Common Grackle": "Icteridae", "Red-winged Blackbird": "Icteridae", "Brown-headed Cowbird": "Icteridae",
    "Baltimore Oriole": "Icteridae",
    "American Robin": "Turdidae", "Gray Catbird": "Mimidae",
    "Cedar Waxwing": "Bombycillidae", "Bohemian Waxwing": "Bombycillidae",
    "Ruby-throated Hummingbird": "Trochilidae", "Brown Creeper": "Certhiidae", "Carolina Wren": "Troglodytidae",
    "Yellow-rumped Warbler": "Parulidae", "Snow Bunting": "Calcariidae",
    "Sharp-shinned Hawk": "Accipitridae", "Cooper's Hawk": "Accipitridae",
    "Wild Turkey": "Phasianidae", "Northern Shrike": "Laniidae",
    "Squirrel": "Sciuridae", "Chipmunk": "Sciuridae",
}
