/* Input to this function is a string representing musical notes in a special ASCII format.
  Your task is to parse this string and return list of integers corresponding to how many beats does each
  not last.

  Here is a legend:
  'o' - whole note, lasts four beats
  'o|' - half note, lasts two beats
  '.|' - quater note, lasts one beat

  >>> parseMusic('o o| .| o| o| .| .| .| .| o o')
  [4, 2, 1, 2, 2, 1, 1, 1, 1, 4, 4]
  */
const parseMusic = (music_string) => {
  const note_map = {'o': 4, 'o|': 2, '.|': 1};
  return music_string.split(' ').filter(x => x != '').map(x => note_map[x]);
}

