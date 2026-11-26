import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').resolve()))
sys.stdout.reconfigure(encoding='utf-8')

raw_text = Path('work/americandad/foxy_spring_breakup_raw.md').read_text(encoding='utf-8')
exp_text = Path('work/americandad/foxy_spring_breakup_rebuilt.md').read_text(encoding='utf-8')

raw_lines = [
    'Okay, troops—briefing: three nights of lasagna, two of orange chicken, and one “mystery casserole” to be opened only under adult supervision. (softer) I’ll be at Mom and Baba’s until Friday. Mostly I’ll be pressing on Baba’s stomach to release gas… or, you know, fart him.',
    'Ah, the ancient art of ancestral toot massage.',
    'It’s bright in here. Morning’s a liar.',
    'That’s… sweet. Gross, but sweet. Like a caramel‑dipped cricket.',
    'When you love someone, you help them let it out—feelings or gastrointestinal rebellion.',
    'Ugh… my stomach’s staging a coup. Maybe I should just stay here, ride it out on the couch—',
    'Ten seconds flat, horizontal—rebellion quelled—',
    'Careful, Mom—one wrong torque and that thing you’re smuggling is gonna ping the Delaware Richter.',
    'Haley.',
    'Sweetie, you sure you’re up for the car ride? My parents would love to see you, but not if you’re—',
    'You look insane, Mom—Instagram filter incarnate. If walking fast was a felony, you’d be doing twenty‑five to life.',
    'Don’t body‑shame the masterpiece. That’s a Botticelli with extra bounce.',
    'Damn right it is—',
    'Still hot. Objectively.',
    'I… don’t think you’re supposed to say that about your own mom.',
    'Ahhhh… that’s better. Felt like I swallowed a weather balloon.',
    'Oh my god, the juxtaposition—snrk! You’re coming with me. Looks like you need farting just like Baba.',
    'Totally normal day in this family. Nothing to see here, just Mom cosplaying as a cartoon dad with a Kardashian rear. Move along.',
    'You’re sick, missy. And now I get to cosplay and take care of you—make me into a sexy nurse, stat!',
    'Ow—cold! Okay, still hot though. You two are gross. Power‑couple gross. Like if Cher and Shrek had a baby.',
    'And I’m the one who needs therapy.',
    'Mmm… I’ve got the touch for healing. And squeezing. (beat) I bill by the squeeze.',
    'Won’t your parents mind if you’re strutting around their house dressed like the night‑shift fantasy of a ’90s music video?',
    'Please—they’ll be relieved the fox goddess Húxiān Niángniáng is watching over us. (thumb at Rainee) You—looking like the Fat God of Fortune? Extra lucky.',
    'I’ve heard of Húxiān Niángniáng. “Fat” isn’t canon, Mom.',
    'Canon now.',
    'Oh, and like—no wild parties, okay? Addendum: I’ll be farting Baba and Rosie O’Donnell here until she’s back to her glorious, problematic self. You two hold the fort. Maybe change the couch covers; we’re downwind.',
    'No parties. Got it. (beat) Maybe. Depends on the definition of “wild.”',
    'Alright, lovebugs. If the house is still standing when we get back, you’re grounded. If it’s not, you’re grounded somewhere with better Wi‑Fi.',
    'I give it six hours before the living room is a nightclub and I’m charging cover.',
    'Venmo accepted. DJ at nine. Bring your own antacid.'
]

all_found = True
for line in raw_lines:
    clean_line = line.replace('‑', '-').replace('—', '--').replace('…', '...').replace('“', '"').replace('”', '"').replace('’', "'")
    clean_exp = exp_text.replace('‑', '-').replace('—', '--').replace('…', '...').replace('“', '"').replace('”', '"').replace('’', "'")
    if clean_line not in clean_exp:
        print(f"MISSING: {line[:50]}...")
        all_found = False

if all_found:
    print("SUCCESS: All 31 dialogue lines 100% preserved!")
