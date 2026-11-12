"""Fun facts for the bird's card on the home page: two or three per species on the starting list, kid-friendly.

Hand-written from well-known natural history (2026-11-12), kept general on purpose: no records or exact numbers
that vary by source. A species missing here (one you added) just shows no facts.
"""

FACTS: dict[str, list[str]] = {
    "Black-capped Chickadee": [
        "Its call says its name: chick-a-dee-dee-dee. More dees can mean a bigger danger nearby.",
        "It hides thousands of seeds each fall and remembers where many of them are.",
        "On cold nights it lowers its body temperature to save energy.",
    ],
    "Blue Jay": [
        "Its feathers aren't really blue: they look blue because of how they bend light.",
        "It can copy the scream of a Red-tailed Hawk, maybe to scare other birds off the food.",
        "It carries acorns in a pouch in its throat and buries them, which helps plant oak trees.",
    ],
    "Northern Cardinal": [
        "Both the male and the female sing.",
        "The male feeds the female beak to beak while they court.",
        "It sometimes fights its own reflection in a window, thinking it's a rival.",
    ],
    "American Goldfinch": [
        "The male is bright yellow in summer and turns olive-brown for the winter.",
        "It eats almost only seeds, and even feeds seeds to its babies.",
        "It nests late in summer, when thistles have fluffy seeds for its nest.",
    ],
    "House Finch": [
        "It was brought from the west to New York as a cage bird, and spread across the East from there.",
        "The male's red comes from the food it eats: more colourful food, redder bird.",
    ],
    "Purple Finch": [
        "The male looks like it was dipped in raspberry juice.",
        "It is easy to mix up with the House Finch: look for a cleaner, rosier head.",
    ],
    "House Sparrow": [
        "It came from Europe and now lives in cities all over the world.",
        "It loves dust baths, fluffing dry dirt through its feathers.",
    ],
    "American Tree Sparrow": [
        "It doesn't live in trees much at all: it nests on the ground in the far north.",
        "It only visits southern Canada and the U.S. in winter.",
    ],
    "Song Sparrow": [
        "Each male can sing several different songs.",
        "Look for the dark spot in the middle of its streaky chest.",
    ],
    "Chipping Sparrow": [
        "Its song is a fast, dry trill that sounds like a sewing machine.",
        "It often lines its nest with soft hair.",
    ],
    "White-throated Sparrow": [
        "Its song sounds like O sweet Canada, Canada, Canada.",
        "Some have white head stripes and some have tan ones.",
    ],
    "White-crowned Sparrow": [
        "Its black-and-white striped head looks like a bike helmet.",
        "It can fly very long distances on migration, even overnight.",
    ],
    "Dark-eyed Junco": [
        "People call it the snowbird because it shows up when winter comes.",
        "It flashes white outer tail feathers when it flies off.",
    ],
    "White-breasted Nuthatch": [
        "It walks headfirst down tree trunks, which few birds can do.",
        "It wedges seeds into bark and hacks them open with its beak: that's where the name comes from.",
        "Its call is a nasal yank-yank, like a tiny toy horn.",
    ],
    "Red-breasted Nuthatch": [
        "It smears sticky pine sap around its nest hole, maybe to keep other animals out.",
        "Its call sounds like a little tin horn.",
    ],
    "Downy Woodpecker": [
        "It is the smallest woodpecker in North America.",
        "Only the male has the red patch on the back of its head.",
        "It looks just like the Hairy Woodpecker, but its beak is much shorter.",
    ],
    "Hairy Woodpecker": [
        "It looks like a big Downy Woodpecker, with a beak almost as long as its head.",
        "It drills into trees to find beetle larvae hiding inside.",
    ],
    "Red-bellied Woodpecker": [
        "Its red belly is so faint it's hard to see: the red cap is what stands out.",
        "Its tongue can reach far past the tip of its beak to grab insects.",
    ],
    "Northern Flicker": [
        "It is a woodpecker that likes to eat ants off the ground.",
        "Its wings flash yellow underneath when it flies in the East.",
    ],
    "Pileated Woodpecker": [
        "It is the biggest woodpecker in most of North America, about the size of a crow.",
        "It digs big rectangular holes in trees looking for carpenter ants.",
    ],
    "Mourning Dove": [
        "Its wings whistle when it takes off.",
        "Its sad-sounding coo is how it got its name.",
        "Parents feed their babies crop milk, a food they make in their throats.",
    ],
    "Rock Pigeon": [
        "It is the pigeon of city streets, and people have kept them for thousands of years.",
        "Pigeons can find their way home from far away.",
    ],
    "European Starling": [
        "It came from Europe: about 100 were let go in New York's Central Park in 1890 and 1891.",
        "It is a great copycat and can imitate other birds and even car alarms.",
        "In winter its shiny feathers are covered in white spots, like stars.",
    ],
    "Common Grackle": [
        "Its shiny black feathers glow purple and bronze in the sun.",
        "It sometimes lets ants crawl on its feathers, which may help clean them.",
    ],
    "Red-winged Blackbird": [
        "The male shows off red and yellow shoulder patches to defend his spot.",
        "It is one of the first birds to come back in spring.",
    ],
    "Brown-headed Cowbird": [
        "It never builds a nest: it lays its eggs in other birds' nests.",
        "It used to follow bison herds to eat the insects they stirred up.",
    ],
    "American Crow": [
        "Crows can recognize people's faces and remember them.",
        "They live in family groups, and older brothers and sisters help raise the babies.",
    ],
    "American Robin": [
        "It finds worms by watching for movement, tilting its head to look.",
        "Its eggs are the famous robin's-egg blue.",
    ],
    "Tufted Titmouse": [
        "It is a cousin of the chickadee, with a little grey crest.",
        "It sometimes pulls hair from animals, even people, to line its nest.",
    ],
    "Pine Siskin": [
        "It comes south in big flocks some winters and hardly at all in others.",
        "Look for yellow flashes in its wings and tail.",
    ],
    "Common Redpoll": [
        "It has a red cap, like a little beret.",
        "It can store seeds in a pouch in its throat to eat later, out of the wind.",
        "It survives cold far below freezing in the Arctic.",
    ],
    "Evening Grosbeak": [
        "Its huge pale beak can crack big seeds.",
        "Its name comes from an old idea that it only sang in the evening.",
    ],
    "Rose-breasted Grosbeak": [
        "The male has a bright rose-red triangle on his white chest.",
        "Its song sounds like a robin that took singing lessons.",
    ],
    "Indigo Bunting": [
        "Like the Blue Jay, its blue comes from light, not from blue colouring.",
        "It migrates at night and finds its way using the stars.",
    ],
    "Baltimore Oriole": [
        "It weaves a hanging nest like a little sock.",
        "It loves oranges and grape jelly at feeders.",
    ],
    "Gray Catbird": [
        "Its call sounds like a cat's meow.",
        "It can copy the songs of other birds and string them together.",
    ],
    "Cedar Waxwing": [
        "Its wingtips look like they were dipped in red wax.",
        "Flocks sometimes pass a berry beak to beak down a branch.",
    ],
    "Ruby-throated Hummingbird": [
        "It beats its wings so fast they hum.",
        "It can fly backwards.",
        "Even though it is tiny, it flies across the Gulf of Mexico on migration.",
    ],
    "Eastern Towhee": [
        "Its song sounds like drink your tea!",
        "It scratches the ground with both feet at once, hopping backwards.",
    ],
    "Fox Sparrow": [
        "It is a big sparrow with fox-red colours.",
        "It kicks through leaves with both feet to find food.",
    ],
    "Brown Creeper": [
        "It climbs up tree trunks in a spiral, then flies down to the bottom of the next tree.",
        "Its brown back looks so much like bark that it's hard to spot.",
    ],
    "Carolina Wren": [
        "It is tiny but sings very loudly: teakettle, teakettle, teakettle!",
        "It has been moving farther north as winters get milder.",
    ],
    "Yellow-rumped Warbler": [
        "Birders call it butter-butt for the yellow patch above its tail.",
        "It can eat waxy berries that most warblers can't digest, so it can stay north longer.",
    ],
    "Snow Bunting": [
        "It nests in the Arctic and visits southern Canada in winter.",
        "A flock lifting off a snowy field looks like a swirl of snowflakes.",
    ],
    "Pine Grosbeak": [
        "It is a big, gentle finch from the northern forests.",
        "It is often so calm that people can walk up close to it.",
    ],
    "Sharp-shinned Hawk": [
        "It is a small hawk that hunts other birds, sometimes at feeders.",
        "It can twist and turn through branches at high speed.",
    ],
    "Cooper's Hawk": [
        "It looks like a bigger Sharp-shinned Hawk, with a more rounded tail.",
        "It surprises small birds by dashing around bushes and buildings.",
    ],
    "Wild Turkey": [
        "Wild turkeys can fly, and they sleep up in trees at night.",
        "The male gobbles and fans his tail to show off.",
    ],
    "Bohemian Waxwing": [
        "It wanders in big flocks looking for fruit, so you never know when it will show up.",
        "It has red waxy tips on its wings, like the Cedar Waxwing, plus rusty feathers under its tail.",
    ],
    "Northern Shrike": [
        "It is a songbird that hunts like a hawk.",
        "It sticks its catch on thorns or barbed wire, like a pantry.",
    ],
    "Canada Jay": [
        "It is also called the whisky jack, and it will take food from people's hands.",
        "It hides food in trees with sticky spit and lays eggs in late winter, when snow still covers the ground.",
    ],
    "Red Crossbill": [
        "The tips of its beak cross over, which helps it pry seeds out of pine cones.",
        "It can nest at any time of year when there are lots of cones, even in winter.",
    ],
    "White-winged Crossbill": [
        "Its crossed beak is made for opening spruce and larch cones.",
        "It moves around a lot, following good cone crops.",
    ],
    "Hoary Redpoll": [
        "It looks like a frosty, paler Common Redpoll.",
        "It lives in the Arctic and is a rare treat at southern feeders.",
    ],
    "Squirrel": [
        "Squirrels bury nuts and forget some of them, which helps new trees grow.",
        "They can turn their back feet around to run headfirst down a tree.",
    ],
    "Chipmunk": [
        "It carries food in stretchy cheek pouches.",
        "It sleeps through most of the winter in its burrow, waking up now and then to eat from its store.",
    ],
}
