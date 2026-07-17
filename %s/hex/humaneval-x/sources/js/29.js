/* Filter an input list of strings only for ones that start with a given prefix.
  >>> filterByPrefix([], 'a')
  []
  >>> filterByPrefix(['abc', 'bcd', 'cde', 'array'], 'a')
  ['abc', 'array']
  */
const filterByPrefix = (strings, prefix) => {
  return strings.filter(x => x.startsWith(prefix));
}

