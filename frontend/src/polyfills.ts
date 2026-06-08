type ObjectConstructorWithHasOwn = ObjectConstructor & {
  hasOwn?: (object: object, property: PropertyKey) => boolean;
};

type ArrayWithAt<T> = Array<T> & {
  at?: (index: number) => T | undefined;
};

type StringPrototypeWithReplaceAll = typeof String.prototype & {
  replaceAll?: (
    searchValue: string | RegExp,
    replaceValue: string,
  ) => string;
};

const objectConstructor = Object as ObjectConstructorWithHasOwn;

if (typeof objectConstructor.hasOwn !== "function") {
  Object.defineProperty(Object, "hasOwn", {
    configurable: true,
    value(object: object, property: PropertyKey): boolean {
      return Object.prototype.hasOwnProperty.call(Object(object), property);
    },
    writable: true
  });
}

if (typeof ([] as ArrayWithAt<unknown>).at !== "function") {
  Object.defineProperty(Array.prototype, "at", {
    configurable: true,
    value<T>(this: T[], index: number): T | undefined {
      const length = this.length;
      const integer = Math.trunc(Number(index)) || 0;
      const offset = integer < 0 ? length + integer : integer;
      return offset >= 0 && offset < length ? this[offset] : undefined;
    },
    writable: true
  });
}

if (typeof (String.prototype as StringPrototypeWithReplaceAll).replaceAll !== "function") {
  Object.defineProperty(String.prototype, "replaceAll", {
    configurable: true,
    value(
      this: string,
      searchValue: string | RegExp,
      replaceValue: string
    ): string {
      if (searchValue instanceof RegExp) {
        if (!searchValue.global) {
          throw new TypeError("String.prototype.replaceAll called with a non-global RegExp argument");
        }
        return this.replace(searchValue, replaceValue);
      }
      const search = String(searchValue);
      if (search === "") {
        return `${replaceValue}${this.split("").join(replaceValue)}${replaceValue}`;
      }
      return this.split(search).join(replaceValue);
    },
    writable: true
  });
}
