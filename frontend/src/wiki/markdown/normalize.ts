export function repairConjoinedFenceHeadings(markdown: string): string {
  return markdown.replace(/^([ \t]*`{3,})[ \t]*(#{1,6}[ \t]+)/gm, "$1\n$2");
}
