"""Cinnamon Wildlands: The Treasure Worth Billions — interactive story.

Loaded *after* wildlands_fishing.py by main.py. The shared
advanced_features_data/Upstash snapshot stores story progress separately from
existing fishing inventories and older Wildlands saves. Story UI is ephemeral,
with a fresh session available through /wildlands story after view expiration.
"""

_WLS_CHAPTERS = (
    'Prologue • An Extremely Important Catastrophe',
    '1 • The Disappearance',
    '2 • The Great Fish Conspiracy',
    '3 • The Vault of Nine Locks',
    '4 • The Marsh of Forgotten Things',
    '5 • The Greatest Heist in Cat History',
    '6 • The Billion-Catnip Treasure',
)
_WLS_COLOR = 0xE9A344
_WLS_REWARD = 100_000
_WLS_MOOD_STOPS = {5, 10, 15, 20, 25}


def _wls_scene(chapter, area, title, text, choices, *, chance=.08):
    """Choice=(label, result, clue, require_correct) — wrong puzzle answers retry."""
    assert len(choices) == 3
    return {'chapter': chapter, 'area': area, 'title': title, 'text': text,
            'choices': choices, 'chance': chance}


_WLS_SCENES = [
    _wls_scene(0,'whispering_woods','A VERY IMPORTANT ANNOUNCEMENT',
        'You hear an enormous crash from Cinnamon’s house. She stands on a table surrounded by fallen cups.\n\n'
        '**Cinnamon:** “EVERYONE! I HAVE LOST SOMETHING MORE IMPORTANT THAN FOOD!”\n'
        '**You:** “Your dignity?”\n**Cinnamon:** “THAT LEFT YEARS AGO. PAY ATTENTION.”\n\n'
        'She claims a hidden treasure is worth **ONE BILLION CATNIP**. The only map is a drawing of a fish.',[
            ('Accept the job','“Excellent,” purrs Cinnamon. “You may now refer to yourself as Assistant Treasure Finder, unpaid until further notice.”','hired',True),
            ('Ask for a contract','Cinnamon hands you a napkin reading: “I, THE CAT, PROMISE SOMETHING.” It is signed in gravy.','napkin_contract',True),
            ('Demand half the treasure','“Half of a billion?” Cinnamon gasps. “Have you even SEEN how many zeros that is?!”','half_billion',True)],chance=0),
    _wls_scene(0,'whispering_woods','The Fish-Shaped Map',
        'The map has three landmarks: a crooked tree, a tiny crown, and a large X that might actually be a squashed mosquito.\n\n'
        '**Cinnamon:** “I designed it myself. Graphic design is my passion.”\n'
        'A black cat wearing expensive sunglasses darts past the window.',[
            ('Chase the sunglasses cat','You chase a suspicious cat for six streets. It turns out to be an elderly accountant. He escapes with your lunch.','sunglasses',True),
            ('Inspect the crown drawing','A little crown is engraved beneath the paper. Someone else has been tracing this map.','crown_mark',True),
            ('Ask Cinnamon who drew the X','“A professional cartographer.” A second later: “It was me, with ketchup.”','ketchup_x',True)],chance=0),
    _wls_scene(0,'whispering_woods','A Contractually Dubious Expedition',
        'Cinnamon packs two biscuits, eight fish, and zero ropes. She says the first clue is hidden in **Whispering Woods**.\n'
        '“If we meet an evil mastermind,” she adds, “I will heroically hide behind you.”',[
            ('Pack a lantern','“Clever,” Cinnamon says, immediately using it to check whether the biscuits are still there.','lantern',True),
            ('Pack extra snacks','“Promoted!” Cinnamon says. You are now Chief Snack Officer. The salary remains zero.','snacks',True),
            ('Request proper directions','Cinnamon points at the fish-shaped map. “North is whichever way smells like tuna.”','directions',True)],chance=.04),

    _wls_scene(1,'whispering_woods','The Tree That Looks Guilty',
        'A crooked oak leans over a forest path. Beneath it lies a brass tag stamped with the letter **A**.\n'
        '**Cinnamon:** “That symbol! I remember... something.”\n'
        '**You:** “What?”\n**Cinnamon:** “My breakfast. Delicious.”',[
            ('Examine the tag','The back is scratched with three small claw marks. A trail of black fur leads east.','brass_a',True),
            ('Look up the tree','An owl charges you five Catnip for directions. Cinnamon refuses on principle. The tag still waits below.','owl_fee',True),
            ('Ask about letter A','“A is the start of something extremely precious,” Cinnamon whispers, then changes the subject.','letter_a',True)]),
    _wls_scene(1,'whispering_woods','The First Suspicious Merchant',
        'At a small clearing, **Rowan the Fishing Rod Merchant** is repairing a rod that looks suspiciously like a fork.\n'
        'He heard a dark cat boasting about a “billion-Catnip acquisition.”',[
            ('Ask Rowan to guide you','Rowan sighs. “I have a shop to run. But I have seen that crown before.” He sketches a route.','rowan_route',True),
            ('Test the fork-shaped rod','You catch a leaf, two boots, and the respect of precisely nobody. Rowan laughs.','fork_rod',True),
            ('Offer Cinnamon as payment','“TRAITOR!” Cinnamon shouts, then quietly asks whether Rowan has snacks.','rowan_trade',True)],chance=.22),
    _wls_scene(1,'whispering_woods','An Invitation from the Baron',
        'A paper airplane strikes Cinnamon’s head. The note reads: “HIS SUPREME FLUFFINESS BARON CLAWDIUS VON SCRATCH III REQUESTS THAT YOU STOP LOOKING FOR HIS TREASURE.”\n'
        'The word HIS is underlined seventeen times.',[
            ('Write a sarcastic reply','You send: “Dear Fluffiness, spelling is free.” Clawdius’s messenger faints.','baron_letter',True),
            ('Follow the messenger','The messenger runs directly into a bush and emerges pretending to be a shrub.','spy_bush',True),
            ('Ask Cinnamon if she knows him','“He lost a Fluffiest Cat competition to me,” she says. “He has never recovered.”','fluffy_rival',True)]),
    _wls_scene(1,'whispering_woods','The Wrong Trail',
        'Two paths split beside a sign: **COAST ←** and **TERRIFYING CASTLE →**.\n'
        'Cinnamon insists the villain would choose the castle. Rowan says the black cat went toward the coast.',[
            ('Follow Rowan’s evidence','Cinnamon grumbles that sensible choices ruin her dramatic speeches. You reach the shore.','coast_route',True),
            ('Follow Cinnamon’s instincts','You spend an hour at a tourist gift shop named Terrifying Castle. Cinnamon buys a hat. Then you reach the shore.','castle_hat',True),
            ('Flip a coin','Cinnamon eats the coin. Rowan leads you toward the coast before the decision gets worse.','coin_incident',True)]),

    _wls_scene(2,'quiet_shore','The Market of Extremely Expensive Lies',
        'The Quiet Shore hosts an auction where everything has a “historical” price tag. One man sells a rock for 10,000 Catnip.\n'
        '**Cinnamon:** “Ridiculous. I own eleven free rocks.”',[
            ('Inspect the auction records','A sealed chest was sold to an agent using the initials **B.C.**.','auction_records',True),
            ('Ask the rock salesman','He offers a family discount: 9,999 Catnip. Cinnamon is offended on your behalf.','rock_scam',True),
            ('Pretend to be a billionaire','The cashier asks for your account balance. Cinnamon loudly changes the subject to soup.','fake_billionaire',True)],chance=.15),
    _wls_scene(2,'quiet_shore','Mira and the Mysterious Bottle',
        '**Mira the Fishing Bait Merchant** finds an old message bottle. Three symbols are stamped under its cork: fish, crown, and paw.\n'
        '“The trick is to choose the one who made the map,” she says. Which symbol belongs to Cinnamon?',[
            ('🐾 Paw — Cinnamon made it','Mira smiles. The bottle opens! Inside is a receipt for a chest shipped to the highlands.','mira_bottle',True),
            ('👑 Crown — clearly royalty','The cork sprays seawater at Cinnamon. “TRY AGAIN, PROFESSOR,” she says.',None,False),
            ('🐟 Fish — the map is a fish','The bottle refuses to open. Cinnamon says the fish is an artistic flourish. Try the maker’s mark.',None,False)],chance=.22),
    _wls_scene(2,'quiet_shore','Breaking News: The Baron Is Rich',
        'A brass loudspeaker rattles. **Baron Clawdius** announces he has acquired “the legendary billion-Catnip treasure,” although he has not opened the chest.\n'
        '**Beans, his assistant:** “Sir, that is generally how auctions work. You buy something before knowing if it’s a potato.”',[
            ('Interrogate the announcement','The speech refers to a vault with **nine locks** in the Stoneback Highlands.','nine_locks',True),
            ('Laugh loudly at the Baron','A nearby guard writes you up for disrespecting royal whiskers.','whisker_ticket',True),
            ('Ask Cinnamon why she is shaking','“I’M NOT PANICKING,” she says, panicking at Olympic speed.','cinnamon_worry',True)]),
    _wls_scene(2,'quiet_shore','Fishy Business',
        'A dockworker agrees to help if you can tell a fish from a suspiciously fish-shaped boot. He holds up three silhouettes.',[
            ('Choose the one with gills','“Finally, someone with a brain,” says the dockworker. He gives you a delivery schedule.','delivery_schedule',True),
            ('Choose the one with shoelaces','You have identified a boot. Cinnamon will never let you forget this. Try again.',None,False),
            ('Choose the one with a handle','That is a kettle. “How have you survived this long?” Beans asks from behind a barrel.',None,False)],chance=.15),

    _wls_scene(3,'stoneback_highlands','The Vault of Nine Locks',
        'Stoneback Highlands shelters a vault covered in complicated warning signs. Nine keyholes surround a plain wooden door.\n'
        '**Cinnamon:** “Nobody can stop us.”\n**You:** “Do you have a key?”\n**Cinnamon:** “I have confidence.”',[
            ('Read the inscription','It says “Eight locks are decorative. The ninth is a doorbell.”','vault_inscription',True),
            ('Poke the obvious button','The vault plays embarrassing elevator music. The door slowly opens.','vault_button',True),
            ('Let Cinnamon pick a lock','Cinnamon scratches the door. It opens because she accidentally presses the doorbell.','vault_claws',True)]),
    _wls_scene(3,'stoneback_highlands','The Archives of Failed Villainy',
        'Inside are meticulous records of Clawdius’s previous hunts. One expedition recovered **seventeen potatoes**, another **a spoon**, and another **Beans himself**.\n'
        'Beans appears behind you. “I have filed three complaints about that last one.”',[
            ('Ask Beans for the real itinerary','Beans reluctantly shares a route through Moonlit Marsh. “Please don’t tell my boss I was useful.”','beans_help',True),
            ('Study the potato expedition','A note reads: “Not enough salt.” Cinnamon calls it a valuable scientific finding.','potato_archives',True),
            ('Ask how Beans fit in a chest','“With difficulty,” Beans says. “Next question.”','beans_chest',True)],chance=.13),
    _wls_scene(3,'stoneback_highlands','The Mandatory Villain Presentation',
        'Clawdius corners you and announces a **97-slide** presentation titled “Why Baron Clawdius Is Better Than Everyone Else.”\n'
        'Slide one is simply a portrait of his paws.',[
            ('Pull the emergency curtain','A hidden exit opens. It was marked “IN CASE OF BORING PRESENTATION.”','curtain_escape',True),
            ('Ask an annoying question','“But what is your evidence?” Clawdius loses an hour. You escape during slide two.','evidence_question',True),
            ('Pretend to be impressed','Clawdius starts slide one again, delighted. Beans silently opens the back door.','fake_applause',True)]),
    _wls_scene(3,'stoneback_highlands','The Missing Cargo',
        'In the fortress yard, workers load a chest marked **FRAGILE: PROBABLY WORTH BILLIONS** onto a boat headed to the marsh.\n'
        'A familiar tiny brass disk is stitched into the shipping label.',[
            ('Copy the shipping label','Destination: Moonlit Marsh, then Frostfall Pass. Delivery priority: “his ego.”','shipping_label',True),
            ('Ask Beans why it is sealed','“Because the Baron thinks touching an ancient chest reduces its resale price.”','chest_sealed',True),
            ('Ask Cinnamon what is inside','“A TREASURE,” she says. “A very treasured treasure. Stop asking suspicious questions.”','cinnamon_evasion',True)]),

    _wls_scene(4,'moonlit_marsh','The Owl Who Knows Almost Everything',
        'The Moonlit Marsh is home to an ancient owl who remembers every item that passed through, but forgets every name.\n'
        '**Owl:** “Welcome, Gregory and Cucumber.”\n**Cinnamon:** “MY NAME IS CINNAMON.”\n**Owl:** “Of course, Cucumber.”',[
            ('Ask about the brass A','“Ah, that mark was connected to a gift from someone very important to Cucumber.”','owl_gift',True),
            ('Offer the owl a riddle','The owl answers before you finish. Cinnamon accuses it of cheating.','owl_riddle',True),
            ('Ask about the Baron','“An over-dressed cat with a tiny crown? Terrible tipper.”','owl_baron',True)]),
    _wls_scene(4,'moonlit_marsh','The Sound of a Memory',
        'The owl recalls seeing the treasure long ago. Not gold, not jewels, but an object carefully guarded by a small orange-brown cat.\n'
        'Cinnamon grows uncharacteristically quiet. “It was given to me by someone I love very much,” she says. Then: “ANYWAY! CRIME!”',[
            ('Give Cinnamon a moment','She nudges your hand once, then demands that nobody tell the Baron.','quiet_memory',True),
            ('Ask who gave it to her','“Someone with excellent taste,” Cinnamon says. “And very patient hands.”','giver_hint',True),
            ('Declare the treasure sacred','“Exactly,” Cinnamon says. “Do not touch it with your grubby adventurer paws.”','sacred_treasure',True)]),
    _wls_scene(4,'moonlit_marsh','The Marsh Lantern Test',
        'Three lights float over the water: a gold crown, a little silver paw, and an enormous sign reading **FREE FISH**.\n'
        'The owl warns the right path follows the symbol that points back to Cinnamon.',[
            ('Follow the silver paw','The lanterns reveal safe stepping stones toward Frostfall Pass.','marsh_paw',True),
            ('Follow the crown','A duck wearing a crown demands tribute. It lets you return to the crossroads.',None,False),
            ('Follow FREE FISH','You find a bucket of suspiciously free lettuce. Cinnamon insists this was a trap.',None,False)]),
    _wls_scene(4,'moonlit_marsh','Operation: Stop the Boat',
        'Beans is attempting to put out smoke rising from the Baron’s boat. The Baron has placed candles next to a sign saying **NO OPEN FLAMES**.\n'
        '**Beans:** “Terribly sorry. He says it makes the treasure look expensive.”',[
            ('Help Beans save the cargo','Beans admits the chest is being delivered to a ceremony in Forgotten Ruins.','beans_alliance',True),
            ('Ask Clawdius about fire safety','“I AM ABOVE SAFETY,” the Baron announces, slipping into the shallow water.','baron_splash',True),
            ('Let Cinnamon direct rescue','She orders everyone to form a tuna-shaped bucket brigade. Somehow, it works.','tuna_brigade',True)],chance=.18),

    _wls_scene(5,'frostfall_pass','The World’s Worst Heist Briefing',
        'In Frostfall Pass, Cinnamon unrolls a 14-page heist plan. It contains exactly three words: **“WE GET BOX.”**\n'
        '“We will steal the chest key,” she explains, “using my brilliance and your questionable expendability.”',[
            ('Suggest disguises','Cinnamon draws a moustache on your face and calls you Agent Whiskers.','disguise_plan',True),
            ('Demand better planning','Cinnamon adds an arrow and the word “SUCCESS” to her diagram.','improved_plan',True),
            ('Ask Beans to join','Beans agrees on condition that nobody makes him attend another slide presentation.','beans_recruit',True)],chance=.16),
    _wls_scene(5,'frostfall_pass','The Snowman Gambit',
        'The Baron’s guards patrol a snowy bridge. Cinnamon has disguised herself as a snowman using a carrot and a paper bucket.\n'
        '**Guard:** “Odd snowman.”\n**Cinnamon:** “THANK YOU.”\n**Guard:** “Wait…”',[
            ('Distract with a giant snowball','The snowball rolls past the guards and into Clawdius’s elaborate statue of himself.','giant_snowball',True),
            ('Pretend to inspect the bridge','Beans produces an official-looking clipboard that reads “VERY BRIDGE.” It works.','bridge_inspector',True),
            ('Ask Cinnamon to act natural','She loudly announces “MEOW” in the voice of a particularly suspicious human. The guards stare.','natural_cat',True)]),
    _wls_scene(5,'frostfall_pass','Which Key Opens the Chest?',
        'You reach a table displaying three keys: a giant golden key, a spoon, and a plain little **silver key marked A**.\n'
        'From the walls you hear Beans: “He always hides the real thing where his ego won’t look.”',[
            ('Take the little silver key','It fits the miniature lock shown on the shipping receipt. The chest can be opened!','silver_key',True),
            ('Take the huge golden key','It is a decorative key to the Baron’s dressing room. Cinnamon admires the wardrobe before retreating.',None,False),
            ('Take the spoon','You have solved dinner, not the mystery. Try again.',None,False)]),
    _wls_scene(5,'frostfall_pass','The Great Escape-ish',
        'As you leave, Clawdius shouts: “STOP! I ORDER YOU TO COME BACK!”\n'
        'His guards hesitate. Beans sighs. “Your Majesty, an order is not the same as a plan.”',[
            ('Race to the Forgotten Ruins','Cinnamon leaps onto the sled and yells “DRIVE, PEASANT!” despite not knowing how sleds work.','ruins_race',True),
            ('Leave a decoy key','Clawdius dramatically opens a box containing a potato. He is personally offended.','decoy_potato',True),
            ('Challenge the Baron to a staring contest','Cinnamon wins in three seconds. Clawdius demands a rematch. You escape.','staring_victory',True)]),

    _wls_scene(6,'forgotten_ruins','The Grandest Grand Reveal',
        'An enormous audience gathers in the Forgotten Ruins. Clawdius stands before the chest under a shower of paper confetti.\n'
        '**Clawdius:** “BEHOLD! SOON I SHALL OWN THE GREATEST TREASURE EVER FOUND!”\n'
        '**Beans:** “Sir, please stop setting confetti on fire.”',[
            ('Enter dramatically','Cinnamon leaps onto the stage and knocks over his crown. “OBJECTION! THAT IS MY BOX!”','dramatic_entrance',True),
            ('Sneak behind Beans','Beans quietly gestures to the safe route, then pretends he saw nothing.','beans_secret',True),
            ('Demand a formal debate','The Baron refuses to answer whether he has ever actually seen the treasure. The crowd murmurs.','debate_opening',True)]),
    _wls_scene(6,'forgotten_ruins','The Final Boss: A Vacuum Cleaner',
        'Clawdius activates his ultimate weapon. A terrifying hum fills the ruins.\n'
        '**Beans:** “Sir… it’s a vacuum cleaner.”\n**Clawdius:** “AND THEY ARE CATS! IT IS GENIUS!”\n'
        'Cinnamon hides behind you with complete confidence in your bravery.',[
            ('Pull the plug','The legendary machine powers down. Clawdius realizes he forgot to build a backup plan.','vacuum_unplugged',True),
            ('Offer Beans a job','Beans switches off the vacuum and says, “Best negotiation I have seen in years.”','beans_new_job',True),
            ('Let Cinnamon intimidate it','Cinnamon gives the vacuum a stern look. You quietly unplug it while she takes all the credit.','intimidation',True)]),
    _wls_scene(6,'forgotten_ruins','The Billion-Catnip Treasure',
        'The chest stands open before you. A golden beam illuminates its mysterious contents.\n'
        'Inside is... **a small, well-loved CHEW TOY**.\n\n'
        '**You:** “...A TOY?!”\n**Cinnamon:** “MY BABYYYY!”\n'
        '**Clawdius:** “I SOLD MY FORTUNE FOR A CHEW TOY?”\n'
        '**Beans:** “Mostly for the 97-slide presentation, sir.”\n\n'
        'Cinnamon holds the toy gently. “Aryan gave this to me. My favourite human. That makes it worth more than a billion Catnip.”',[
            ('Ask about your promised reward','Cinnamon produces a pouch. “100,000 Catnip!” You protest. “The TREASURE is worth billions,” she says. “I never said YOU were.”','ending_reward',True),
            ('Tell Cinnamon it was worth the trip','“Aw,” Cinnamon says. Then she hands you 100,000 Catnip. “Contract complete, Assistant Treasure Finder!”','ending_friend',True),
            ('Ask Clawdius if he wants a refund','“I DEMAND A REFUND!” he screams. Beans hands you 100,000 Catnip on Cinnamon’s behalf and resigns.','ending_baron',True)],chance=0),
]



# Story graph detours. Branches fold back into the same main mystery,
# but choices leave durable state and dialogue callbacks.
_WLS_BRANCHES = {
    'half_talk': _wls_scene(0, 'whispering_woods', 'THE FIFTY-PERCENT CRISIS',
        'Cinnamon drags over a cardboard box labelled NEGOTIATION TABLE. '
        '"FIFTY PERCENT? I asked for an adventurer, not a BUSINESS PARTNER!"\n'
        'Beans arrives with a purple crayon and demands your final offer.', [
            ('Hold firm at 50%', 'Cinnamon agrees to put half the treasure in writing. "You drive a TERRIBLE bargain. For me."', 'deal_half', True),
            ('Compromise at 25%', 'She folds her paws. "Twenty-five. FINAL OFFER." Beans starts the paperwork.', 'deal_quarter', True),
            ('Admit it was a joke', '"You have taken three years off my whiskers." She burns the draft contract.', 'deal_joke', True)]),
    'half_contract': _wls_scene(0, 'whispering_woods', 'THE WORLD’S WORST CONTRACT',
        'A napkin contract promises you 50% of whatever the chest contains. '
        'Beans witnesses it while Cinnamon refuses to make eye contact.', [
            ('Sign it', '"Fine. My extortionate business associate may now have a map." The ink dries.', 'half_signed', True),
            ('Let Cinnamon inspect the chest first', '"That... is surprisingly nice," she admits. She signs.', 'half_kind', True),
            ('Demand a signing bonus fish', '"ABSOLUTELY NOT," she yells, but signs anyway.', 'half_fish', True)]),
    'quarter_contract': _wls_scene(0, 'whispering_woods', 'THE QUARTER-SHARE TREATY',
        'Cinnamon draws four squares and a fish to explain twenty-five percent. '
        'You notice she has erased the word "unpaid."', [
            ('Sign the fair deal', 'Both of you sign. For once, Cinnamon looks impressed.', 'quarter_signed', True),
            ('Ask Beans to witness', 'Beans adds "No dramatic betrayal" to the document. Cinnamon reluctantly agrees.', 'beans_witness', True),
            ('Trade your share for a clue', 'Cinnamon reveals she recognizes the crown on the map. Trust wins over money.', 'trade_share', True)]),
    'contract_review': _wls_scene(0, 'whispering_woods', 'THE SECRET FISH CLAUSE',
        'The gravy-stained employment contract says Cinnamon gets EVERY fish found. '
        '"It is a completely normal condition," she claims.', [
            ('Negotiate 25% of the treasure', 'Cinnamon signs a revised contract and complains about lawyers.', 'contract_quarter', True),
            ('Accept the fish clause', 'Cinnamon hands you the hidden map pocket. "You trust me; I trust you."', 'contract_trust', True),
            ('Get Beans as a witness', 'Beans stamps the napkin. "This is legally ridiculous but I have seen worse."', 'contract_beans', True)]),
    'employment': _wls_scene(0, 'whispering_woods', 'THE UNPAID JOB INTERVIEW',
        'Cinnamon wears spectacles and asks one question: "WHAT WOULD YOU SAVE FIRST: ME OR THE TREASURE?"', [
            ('Protect Cinnamon', '"Good answer," she purrs. "You get first pick of the emergency biscuits."', 'save_cat', True),
            ('Protect the map', '"Efficient but concerning," she says. She gives you a waterproof folder.', 'save_map', True),
            ('Ask for lunch breaks', '"One tuna break per three emergencies." She appoints you Chief Snack Officer.', 'lunch_contract', True)]),
    'rowan_dispute': _wls_scene(1, 'whispering_woods', 'CINNAMON IS NOT LEGAL TENDER',
        '"YOU TRIED TO TRADE ME FOR A FISHING ROD!" Cinnamon shouts. '
        'Rowan says he will show you the coast road only if you repair this diplomatic disaster.', [
            ('Apologize to Cinnamon', 'She reluctantly forgives you. "This is your ONE betrayal allowance."', 'rowan_sorry', True),
            ('Offer Rowan your own snacks', 'He points out the road. Cinnamon keeps reminding you of the betrayal.', 'rowan_snacks', True),
            ('Ask Beans to mediate', 'Beans writes a non-transferable-cat treaty. Rowan approves the route.', 'rowan_beans', True)]),
    'beans_rescue': _wls_scene(4, 'moonlit_marsh', 'BEANS REMEMBERS',
        'You pull Beans and the cargo ashore. "You helped me when you did not have to," he says. '
        'He can get you past the Baron’s fortress guards.', [
            ('Trust Beans with the route', 'Beans gives you a coded key. "Show this to the north guard."', 'beans_route', True),
            ('Keep his help a secret', 'He draws a back entrance. "Nobody else knows this exists."', 'beans_secret_route', True),
            ('Recruit Beans to your crew', 'Beans joins you. "I am done making PowerPoints for that villain."', 'beans_recruited', True)]),
}
_WLS_ENTRY = {(0, 0): 'employment', (0, 1): 'contract_review',
              (0, 2): 'half_talk', (4, 2): 'rowan_dispute',
              (18, 0): 'beans_rescue'}
_WLS_NEXT = {('half_talk', 0): 'half_contract', ('half_talk', 1): 'quarter_contract'}
_WLS_EFFECTS = {
    'deal_half': {'treasure_deal': 'half', 'trust': -2, 'respect': 2},
    'deal_quarter': {'treasure_deal': 'quarter', 'respect': 1},
    'half_kind': {'trust': 2}, 'half_fish': {'trust': -1},
    'trade_share': {'treasure_deal': 'none', 'trust': 3},
    'contract_quarter': {'treasure_deal': 'quarter'},
    'contract_trust': {'trust': 2}, 'save_cat': {'trust': 2},
    'rowan_sorry': {'trust': 2}, 'rowan_snacks': {'trust': -1},
    'beans_witness': {'beans_friendship': 1},
    'contract_beans': {'beans_friendship': 1},
    'rowan_beans': {'beans_friendship': 1},
    'beans_route': {'beans_friendship': 2},
    'beans_secret_route': {'beans_friendship': 2},
    'beans_recruited': {'beans_friendship': 3},
}


def _wls_apply_choice(rec, index, option_index, branch=None):
    """Apply a narrative decision exactly once after view-state validation."""
    scene = _WLS_BRANCHES[branch] if branch else _WLS_SCENES[index]
    opt = scene['choices'][option_index]
    if not opt[3]:
        return False  # Repeat puzzle choice without changing state.
    history = rec.setdefault('history', [])
    history.append({'scene': branch if branch else index, 'choice': opt[0]})
    del history[:-80]
    rec.setdefault('flags', {})
    rec.setdefault('relationship', {})
    rec.setdefault('clues', [])
    if opt[2]:
        rec['flags'][opt[2]] = True
        if opt[2] not in rec['clues']:
            rec['clues'].append(opt[2])
    for key, value in _WLS_EFFECTS.get(opt[2], {}).items():
        if key == 'treasure_deal':
            rec[key] = value
        else:
            rel = rec['relationship']
            rel[key] = max(-9, min(9, int(rel.get(key, 0)) + value))
    if not branch:
        if index == 4 and option_index == 2:
            rel = rec['relationship']
            rel['trust'] = int(rel.get('trust', 0)) - 2
        if index == 19 and option_index == 2:
            rel = rec['relationship']
            rel['beans_friendship'] = int(rel.get('beans_friendship', 0)) + 1
        rec['index'] = index + 1
        rec['branch'] = _WLS_ENTRY.get((index, option_index))
    else:
        rec['branch'] = _WLS_NEXT.get((branch, option_index))
    return True


def _wls_echo(rec, index):
    """Small later callbacks mean paths can reunite without erasing consequences."""
    flags = rec.get('flags', {})
    rel = rec.get('relationship', {})
    deal = rec.get('treasure_deal', 'none')
    notes = []
    if index == 1:
        if deal == 'half':
            notes.append('**Cinnamon:** "My EXTORTIONATE business partner may now inspect the map too."')
        elif deal == 'quarter':
            notes.append('**Cinnamon:** "My twenty-five-percent consultant may inspect the map."')
        elif flags.get('contract_trust'):
            notes.append('Cinnamon reveals the secret map pocket because you trusted her earlier.')
    if index == 6 and flags.get('rowan_trade'):
        notes.append('Cinnamon guards the fork in the road. "Please do not try to SELL ME again."')
    if index == 13 and deal == 'half':
        notes.append('The Baron offers you sixty percent. **Cinnamon:** "DO NOT EVEN THINK ABOUT IT, MR FIFTY-PERCENT!"')
    if index == 19 and int(rel.get('beans_friendship', 0)) >= 2:
        notes.append('A secret coded key arrives from Beans. Your marsh rescue has opened a safer way in.')
    if index == 23:
        if flags.get('beans_recruited'):
            notes.append('Beans leaves the Baron’s side and joins you. "I told you I would help."')
        if deal == 'half':
            notes.append('**Cinnamon:** "Remember. We have a CONTRACT."')
    if index == 25:
        if deal == 'half':
            notes.append('**Cinnamon:** "Technically you own HALF A CHEW TOY. Never touch your half."')
        elif deal == 'quarter':
            notes.append('**Cinnamon:** "You may admire your imaginary quarter of Mr. Squeaks."')
        elif int(rel.get('trust', 0)) >= 2:
            notes.append('Cinnamon shares a quiet moment. "You did not even ask for a share. Thank you."')
        if int(rel.get('beans_friendship', 0)) >= 2:
            notes.append('Beans salutes you: "You earned a friend, not just a clue."')
    return '\n\n'.join(notes)



def _wls_player(guild_id, user_id):
    top = advanced_features_data.setdefault('wildlands_story_v2', {}).setdefault(str(guild_id), {})
    rec = top.setdefault(str(user_id), {})
    rec.setdefault('index', 0)
    rec.setdefault('clues', [])
    rec.setdefault('history', [])
    rec.setdefault('complete', False)
    rec.setdefault('reward_paid', False)
    rec.setdefault('branch', None)
    rec.setdefault('flags', {})
    rec.setdefault('relationship', {})
    rec.setdefault('treasure_deal', 'none')
    rec.setdefault('replay', False)
    return rec


def _wls_embed(interaction, title, body):
    """Shared Wildlands look: high-contrast title and concise readable sections."""
    embed = discord.Embed(title=('📖 ' + str(title))[:256],
                          description=str(body)[:3800], color=0xD97732)
    embed.set_author(name="🐈 CINNAMON · THE BILLION-CATNIP MYSTERY")
    embed.set_footer(text="Wildlands • Your decisions are saved • /wildlands story-journal")
    return embed


def _wls_scene_embed(interaction, rec):
    idx = min(max(0, int(rec['index'])), len(_WLS_SCENES) - 1)
    branch = rec.get('branch')
    scene = _WLS_BRANCHES.get(branch) if branch else _WLS_SCENES[idx]
    if scene is None:
        rec['branch'] = None
        scene = _WLS_SCENES[idx]
    count = len(_WLS_SCENES)
    chapter = _WLS_CHAPTERS[scene['chapter']]
    progress = min(8, int(((idx + 1) / count) * 8))
    bar = "▰" * progress + "▱" * (8 - progress)
    clues = len(rec.get("clues", []))
    echo = _wls_echo(rec, idx) if not rec.get('branch') else ''
    e = _wls_embed(interaction, scene['title'],
                   scene['text'][:2800] + ('\n\n' + echo if echo else '') + "\n\n**🐾 YOUR MOVE**\nChoices shape later scenes.")
    e.add_field(name="🗺️ Region", value=_wlf_area(scene['area'])[1], inline=True)
    e.add_field(name="🔎 Clues", value=f"{clues} found", inline=True)
    e.add_field(name="📊 Progress", value=f"{bar}  **{idx + 1}/{count}**", inline=False)
    e.set_footer(text=f"{chapter} • {'Detour' if rec.get('branch') else 'Scene'} {idx + 1}/{count} • Choices are remembered")
    return e


class _WLSChoice(discord.ui.Button):
    def __init__(self, idx, data):
        super().__init__(label=data[0][:80],style=discord.ButtonStyle.secondary,row=idx)
        self.option_idx = idx

    async def callback(self, interaction):
        await self.view.pick(interaction, self.option_idx)


class _WLSChoiceView(discord.ui.View):
    def __init__(self, owner_id, index, branch=None):
        super().__init__(timeout=900)
        self.owner_id, self.index, self.branch = owner_id, index, branch
        scene = _WLS_BRANCHES[branch] if branch else _WLS_SCENES[index]
        for idx, opt in enumerate(scene['choices']):
            self.add_item(_WLSChoice(idx, opt))

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message('🐈 This adventure belongs to someone else! Open `/wildlands story` to play your own.',ephemeral=True)
            return False
        return True

    async def pick(self, interaction, option_idx):
        if not interaction.guild:
            return await interaction.response.send_message('Use Wildlands in a server.',ephemeral=True)
        g,u=interaction.guild.id, interaction.user.id
        rec=_wls_player(g,u)
        if rec['complete'] or int(rec['index']) != self.index or rec.get('branch') != self.branch:
            return await interaction.response.send_message('Your adventure moved on! Use `/wildlands story` to resume.',ephemeral=True)
        await interaction.response.defer()  # Merchant channel creation may take longer than Discord's 3s ACK window.
        if rec.get('complete') or int(rec.get('index',0)) != self.index or rec.get('branch') != self.branch:
            return await interaction.edit_original_response(
                embed=_wls_embed(interaction,'🐾 Cinnamon Is One Step Ahead',
                    'This choice was already recorded. Use `/wildlands story` to resume.'),view=None)
        scene=_WLS_BRANCHES[self.branch] if self.branch else _WLS_SCENES[self.index]
        opt=scene['choices'][option_idx]
        if not opt[3]:
            return await interaction.edit_original_response(embed=_wls_embed(interaction,'🐾 That Was... A Choice',
                opt[1]+'\n\nTry another option; Cinnamon says we have a BILLION reasons to keep going.'),view=_WLSChoiceView(u,self.index,self.branch))
        _wls_apply_choice(rec, self.index, option_idx, self.branch)
        if rec['index']<len(_WLS_SCENES):
            next_area=_WLS_SCENES[rec['index']]['area']
            player=_wlf_player(g,u)
            if next_area not in player['areas']:
                player['areas'].append(next_area)
        notes=opt[1]
        if self.branch is None and self.index == len(_WLS_SCENES)-1:
            # Award exactly once; do not use player-provided currency values.
            if not rec.get('reward_paid'):
                lock=_WLF_PURCHASE_LOCKS.setdefault(g,asyncio.Lock())
                async with lock:
                    if not rec.get('reward_paid'):
                        before=economy_balance(g,u)
                        economy_balances[(g,u)]=before+_WLS_REWARD
                        rec['reward_paid']=True
                        rec['complete']=True
                        await bd_save_data()
                try:
                    await economy_log(g,title='🏆 Cinnamon Wildlands story completed',fields=[
                        ('Member ID',u),('Reward Catnip',_WLS_REWARD),('Story','The Treasure Worth Billions')])
                except Exception:
                    log.exception('Wildlands story reward saved; achievement log failed')
            else:
                rec['complete']=True
            access=await _wlf_award_story_access(interaction)
            return await interaction.edit_original_response(embed=_wls_embed(interaction,'🏆 THE TREASURE WORTH BILLIONS',
                '🎉 **ADVENTURE COMPLETE!**\n\n'+notes+'\n\n'
                '**The treasure:** Cinnamon’s favourite chew toy from Aryan.\n'
                '**Your reward:** **100,000 Catnip** (once per player).\n'
                '**Cinnamon’s happiness:** INFINITE.\n**Your financial expectations:** DESTROYED.\n'
                +access+'\n\n🎣 The Rod and Bait Merchants are available to you forever.'),view=None)
        await bd_save_data()
        if not self.branch and not rec.get('replay') and scene['chance']:
            notes += await _wlf_attempt_merchant(interaction.guild,finder=interaction.user,
                                                  announce_channel=interaction.channel,
                                                  chance=scene['chance'])
        if not self.branch and not rec.get('branch') and rec['index'] in _WLS_MOOD_STOPS:
            embed=_wls_embed(interaction,'🐈 Cinnamon’s Very Serious Survey',
                notes+'\n\n**Cinnamon:** “So... ARE YOU HAVING FUN? Be honest, but consider that my feelings are made of delicate fluff.”')
            return await interaction.edit_original_response(embed=embed,view=_WLSMoodView(u,rec['index']))
        followup = ('\n\n**A new scene has opened because of your decision.**' if rec.get('branch') else '\n\n*The expedition carries your decision forward.*')
        embed=_wls_embed(interaction,'✨ Your Decision Changes Things',notes + followup)
        await interaction.edit_original_response(embed=embed,view=_WLSContinue(u))


class _WLSContinue(discord.ui.View):
    def __init__(self, owner_id):
        super().__init__(timeout=900)
        self.owner_id=owner_id

    async def interaction_check(self, interaction):
        if interaction.user.id!=self.owner_id:
            await interaction.response.send_message('This is not your adventure. Open `/wildlands story`.',ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Continue the adventure ▶',style=discord.ButtonStyle.success)
    async def advance(self,interaction,button):
        rec=_wls_player(interaction.guild.id,interaction.user.id)
        if rec['complete']:
            return await interaction.response.edit_message(embed=_wls_embed(interaction,'🏆 Adventure Complete',
                'Cinnamon recovered her most precious chew toy. Your reward was 100,000 Catnip. She still insists it is worth ONE BILLION.'),view=None)
        idx=min(len(_WLS_SCENES)-1,max(0,int(rec['index'])))
        await interaction.response.edit_message(embed=_wls_scene_embed(interaction,rec),view=_WLSChoiceView(interaction.user.id,idx,rec.get('branch')))


class _WLSMoodView(discord.ui.View):
    def __init__(self,owner_id,index):
        super().__init__(timeout=900)
        self.owner_id,self.index=owner_id,index

    async def interaction_check(self,interaction):
        if interaction.user.id!=self.owner_id:
            await interaction.response.send_message('Only the adventurer can answer Cinnamon’s survey.',ephemeral=True)
            return False
        return True

    @discord.ui.button(label='YES! 😸',style=discord.ButtonStyle.success)
    async def yes(self,interaction,button):
        await interaction.response.edit_message(embed=_wls_embed(interaction,'🐈 Excellent Review',
            '“FIVE STARS!” Cinnamon declares. “I will frame your review next to my photo of myself.”'),view=_WLSContinue(self.owner_id))

    @discord.ui.button(label='I am bored 😴',style=discord.ButtonStyle.danger)
    async def bored(self,interaction,button):
        await interaction.response.edit_message(embed=_wls_embed(interaction,'🚨 EMERGENCY MOTIVATION',
            '**Cinnamon:** “BORED?! DID YOU FORGET?! **ONE. BILLION. CATNIP.**”\n\n'
            'She gestures furiously at a map drawn on a fish. “Think of the luxury! The treats! THE TREATS!”\n\n'
            '*She does not clarify whether you will receive the entire billion.*'),view=_WLSContinue(self.owner_id))

    @discord.ui.button(label='Just give me the next scene ▶',style=discord.ButtonStyle.secondary)
    async def skip(self,interaction,button):
        rec=_wls_player(interaction.guild.id,interaction.user.id)
        await interaction.response.edit_message(embed=_wls_scene_embed(interaction,rec),view=_WLSChoiceView(self.owner_id,rec['index'],rec.get('branch')))


@wildlands_art_group.command(name='story',description='Play Cinnamon’s funny, mysterious, choice-driven treasure adventure')
@app_commands.guild_only()
async def wildlands_story(interaction:discord.Interaction):
    rec=_wls_player(interaction.guild.id,interaction.user.id)
    if rec['complete']:
        await interaction.response.defer(ephemeral=True)
        access=await _wlf_award_story_access(interaction)
        return await interaction.followup.send(embed=_wls_embed(interaction,'🏆 Adventure Already Complete',
            'Cinnamon found her chew toy from Aryan. You claimed your one-time **100,000 Catnip** reward. '\
            'You have permanent access to both merchant shops!\n\n'
            '“I SAID THE *TREASURE* WAS WORTH A BILLION,” Cinnamon reminds you.'+access),ephemeral=True)
    idx=min(len(_WLS_SCENES)-1,max(0,int(rec['index'])))
    await interaction.response.send_message(embed=_wls_scene_embed(interaction,rec),view=_WLSChoiceView(interaction.user.id,idx),ephemeral=True)



@wildlands_art_group.command(name='story-restart', description='Replay the Wildlands mystery from the beginning; one-time reward stays claimed')
@app_commands.describe(confirm='Set True to reset your story decisions and start again')
@app_commands.guild_only()
async def wildlands_story_restart(interaction: discord.Interaction, confirm: bool = False):
    if not confirm:
        return await interaction.response.send_message(
            '🐈 Restarting wipes your CURRENT story decisions, clues and relationships. '
            'Your completed reward and fishing gear stay safe. '
            'Run /wildlands story-restart with confirm=True when ready.',
            ephemeral=True)
    old = _wls_player(interaction.guild.id, interaction.user.id)
    was_paid = bool(old.get('reward_paid'))
    old.update({'index': 0, 'branch': None, 'clues': [], 'history': [],
                'flags': {}, 'relationship': {}, 'treasure_deal': 'none',
                'complete': False, 'reward_paid': was_paid, 'replay': True})
    # No second one-time payout and no repeat merchant-opening rolls on replays.
    await bd_save_data()
    await interaction.response.send_message(
        embed=_wls_scene_embed(interaction, old),
        view=_WLSChoiceView(interaction.user.id, 0), ephemeral=True)


@wildlands_art_group.command(name='story-journal',description='Review your story progress and important discoveries')
@app_commands.guild_only()
async def wildlands_story_journal(interaction:discord.Interaction):
    rec=_wls_player(interaction.guild.id,interaction.user.id)
    idx=min(len(_WLS_SCENES)-1,max(0,int(rec['index'])))
    area=_wls_scene_area=(_WLS_SCENES[idx]['area'] if not rec['complete'] else 'forgotten_ruins')
    recent=rec.get('history',[])[-4:]
    rows=['• '+v['choice'] for v in recent]
    rel=rec.get('relationship', {})
    msg=(f'**Status:** {"✅ Story completed" if rec["complete"] else "In progress"}\n'
         f'**Scene:** {min(int(rec["index"])+1,len(_WLS_SCENES))}/{len(_WLS_SCENES)}\n'
         f'**Region:** {_wlf_area(area)[1]}\n'
         f'**Clues and memories:** {len(rec.get("clues", []))}\n'
         f'**Treasure deal:** {rec.get("treasure_deal", "none").title()}\n'
         f'**Cinnamon trust:** {int(rel.get("trust", 0)):+d} · **Beans alliance:** {int(rel.get("beans_friendship", 0)):+d}\n'
         f'**Current route:** {rec.get("branch") or "Main expedition"}\n'
         f'**Recent decisions:**\n'+ ('\n'.join(rows) if rows else 'No decisions yet')+'\n\n'
         '**Next:** `/wildlands story` to continue.\n'
         '🎣 Fish, rod, bait and merchant shops stay part of the adventure.')
    await interaction.response.send_message(embed=_wls_embed(interaction,'📖 Your Adventure Journal',msg),ephemeral=True)


@wildlands_art_group.command(name='story-help',description='How Cinnamon’s interactive mystery and merchant shops work')
@app_commands.guild_only()
async def wildlands_story_help(interaction:discord.Interaction):
    await interaction.response.send_message(embed=_wls_embed(interaction,'🐈 The Rules (As Written by a Cat)',
        '**Play:** `/wildlands story` to begin or resume; select dialogue and puzzle choices with buttons.\n'
        '**Replay:** `/wildlands story-restart confirm:True` resets only the story route, not the one-time payout or fishing gear.\n'
        '**Track:** `/wildlands story-journal`. Branches, relationships and negotiated deals influence later scenes. Bad puzzle guesses do not lose progress.\n'
        '**Merchants:** Story decisions and `/wildlands gather` can discover a merchant. The shop opens to everyone for **2 hours** in its own channel.\n'
        '**Finder bonus:** 10% of other players’ purchases made inside the open shop channel. The bonus is extra Catnip, not a surcharge.\n'
        '**Forever access:** Finish this adventure and both shop channels stay open **for you** even between public discoveries.\n'
        '**Grand prize:** Complete the whole story for **100,000 Catnip once**.\n'
        '**Cinnamon’s legal statement:** “ALL TREASURE VALUATIONS ARE PERSONAL OPINIONS AND NONE OF YOUR BUSINESS.”'),ephemeral=True)