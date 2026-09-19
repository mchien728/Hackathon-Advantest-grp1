import random


class Scenario:
    def __init__(self, kind, magnitude, start, keys=None, site=None):
        self.kind = kind
        self.mag = magnitude
        self.start = start
        self.keys = None if keys is None else set(keys)
        self.site = site

    def apply(self, td, key, site, x, mu, sigma):
        if td < self.start or (self.keys is not None and key not in self.keys):
            return x
        if self.kind == "mean_shift":
            return x + self.mag * sigma
        if self.kind == "mean_drift":
            return x + self.mag * sigma * (td - self.start)
        if self.kind == "variance_change":
            return mu + (x - mu) * self.mag
        if self.kind == "site_imbalance":
            return x + self.mag * sigma if site == self.site else x
        if self.kind == "outlier_burst":
            return x + self.mag * sigma if site == self.site and td < self.start + 5 else x
        raise ValueError(f"unknown scenario kind: {self.kind}")


def generate(tests, n_td, sites=4, scenarios=(), seed=0):
    rng = random.Random(seed)
    gauss = rng.gauss
    items = [(k, mu, sg) for k, (mu, sg) in tests.items()]
    for td in range(n_td):
        active = [s for s in scenarios if td >= s.start]
        batch = []
        for key, mu, sg in items:
            for site in range(1, sites + 1):
                x = mu + sg * gauss(0.0, 1.0)
                for s in active:
                    x = s.apply(td, key, site, x, mu, sg)
                batch.append((key, site, x))
        yield td, batch


if __name__ == "__main__":
    demo = {"Main.Suite1#CP": (1.15, 0.02)}
    for td, batch in generate(demo, 3, scenarios=[Scenario("site_imbalance", 3.0, 1, site=4)]):
        print(td, [(s, round(x, 3)) for _, s, x in batch])
