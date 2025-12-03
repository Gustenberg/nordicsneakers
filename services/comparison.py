"""
Sammenligningstjeneste
Sammenligner WTB efterspørgselsopslag mod dit butiks produkter.
"""
from difflib import SequenceMatcher
from typing import Optional

import database
from config import setup_logging

logger = setup_logging("comparison")


class ComparisonService:
    """Tjeneste til sammenligning af WTB efterspørgsel mod dine produkter."""

    def __init__(self):
        self.similarity_threshold = 0.75  # Minimum lighed for fuzzy matching

    def compare(self) -> dict:
        """
        Sammenlign WTB opslag mod dine produkter.
        Returnerer kategoriserede resultater.
        """
        # Hent data fra database
        wtb_demand = database.get_wtb_demand_summary()
        my_products = database.get_all_my_products()

        # Byg opslagsindekser
        my_products_by_sku = {p['sku'].upper(): p for p in my_products if p.get('sku')}
        my_products_by_name = {self._normalize_name(p['name']): p for p in my_products}

        results = {
            "missing": [],      # Efterspurgt men IKKE i din butik
            "in_stock": [],     # Du har det OG der er efterspørgsel
            "no_demand": [],    # Du har det men INGEN efterspørgsel
            "summary": {
                "total_wtb_items": len(wtb_demand),
                "total_my_products": len(my_products),
                "missing_count": 0,
                "in_stock_count": 0,
                "no_demand_count": 0
            }
        }

        matched_product_ids = set()

        # Tjek hvert WTB element mod vores produkter
        for wtb_item in wtb_demand:
            match = self._find_match(wtb_item, my_products_by_sku, my_products_by_name, my_products)

            item_data = {
                "wtb_name": wtb_item["name"],
                "wtb_sku": wtb_item.get("sku"),
                "brand": wtb_item.get("brand"),
                "demand_count": wtb_item.get("demand_count", 1),
                "stores_wanting": wtb_item.get("stores", "").split(",") if wtb_item.get("stores") else [],
                "wtb_price_min": wtb_item.get("min_price"),
                "wtb_price_max": wtb_item.get("max_price"),
                "sizes_wanted": wtb_item.get("sizes", "").split(",") if wtb_item.get("sizes") else [],
                "image_url": wtb_item.get("image_url")
            }

            if match:
                matched_product_ids.add(match["id"])
                item_data.update({
                    "status": "in_stock",
                    "my_product_name": match["name"],
                    "my_product_sku": match.get("sku"),
                    "my_product_price": match.get("price"),
                    "my_product_url": match.get("url"),
                    "my_sizes_available": match.get("sizes", []),
                    "my_product_image_url": match.get("image_url")
                })
                # Foretræk produktbillede over WTB billede hvis tilgængeligt
                if match.get("image_url"):
                    item_data["image_url"] = match.get("image_url")
                results["in_stock"].append(item_data)
            else:
                item_data["status"] = "missing"
                results["missing"].append(item_data)

        # Find produkter uden efterspørgsel
        for product in my_products:
            if product["id"] not in matched_product_ids:
                results["no_demand"].append({
                    "status": "no_demand",
                    "my_product_name": product["name"],
                    "my_product_sku": product.get("sku"),
                    "my_product_price": product.get("price"),
                    "my_product_url": product.get("url"),
                    "my_sizes_available": product.get("sizes", []),
                    "image_url": product.get("image_url")
                })

        # Sorter resultater
        results["missing"].sort(key=lambda x: x.get("demand_count", 0), reverse=True)
        results["in_stock"].sort(key=lambda x: x.get("demand_count", 0), reverse=True)
        results["no_demand"].sort(key=lambda x: x.get("my_product_name", ""))

        # Opdater oversigt
        results["summary"]["missing_count"] = len(results["missing"])
        results["summary"]["in_stock_count"] = len(results["in_stock"])
        results["summary"]["no_demand_count"] = len(results["no_demand"])

        logger.debug(f"Sammenligning færdig: {results['summary']}")
        return results

    def _find_match(self, wtb_item: dict, by_sku: dict, by_name: dict, all_products: list) -> Optional[dict]:
        """Find et matchende produkt til et WTB element."""
        # Prøv eksakt SKU match først
        if wtb_item.get("sku"):
            sku = wtb_item["sku"].upper()
            if sku in by_sku:
                return by_sku[sku]

        # Prøv eksakt navn match
        normalized = self._normalize_name(wtb_item["name"])
        if normalized in by_name:
            return by_name[normalized]

        # Prøv fuzzy navn matching
        best_match = None
        best_score = 0

        for product in all_products:
            score = self._similarity(wtb_item["name"], product["name"])

            # Boost score hvis brand matcher
            if wtb_item.get("brand") and product.get("brand"):
                if wtb_item["brand"].lower() == product["brand"].lower():
                    score += 0.1

            if score > best_score and score >= self.similarity_threshold:
                best_score = score
                best_match = product

        return best_match

    def _normalize_name(self, name: str) -> str:
        """Normaliser produktnavn til sammenligning."""
        if not name:
            return ""
        # Små bogstaver, fjern ekstra mellemrum, fjern almindelige ord
        name = name.lower().strip()
        name = " ".join(name.split())  # Normaliser mellemrum
        # Fjern almindelige ord der ikke hjælper med matching
        for word in ["the", "new", "mens", "womens", "men's", "women's"]:
            name = name.replace(f" {word} ", " ")
        return name

    def _similarity(self, a: str, b: str) -> float:
        """Beregn lighed mellem to strenge."""
        if not a or not b:
            return 0.0
        a = self._normalize_name(a)
        b = self._normalize_name(b)
        return SequenceMatcher(None, a, b).ratio()

    def get_missing_items(self, min_demand: int = 1) -> list[dict]:
        """Hent elementer der er efterspurgt men mangler i din butik."""
        results = self.compare()
        return [
            item for item in results["missing"]
            if item.get("demand_count", 0) >= min_demand
        ]

    def get_opportunities(self, limit: int = 20) -> list[dict]:
        """Hent top muligheder - højest efterspurgte elementer du mangler."""
        results = self.compare()
        return results["missing"][:limit]

    def export_to_csv(self, filepath: str, category: str = "missing"):
        """Eksporter sammenligningsresultater til CSV."""
        import csv

        results = self.compare()
        items = results.get(category, [])

        if not items:
            logger.warning(f"Ingen elementer at eksportere for kategori: {category}")
            return False

        # Bestem felter baseret på kategori
        if category == "missing":
            fields = ["wtb_name", "wtb_sku", "brand", "demand_count", "wtb_price_min", "wtb_price_max"]
        elif category == "in_stock":
            fields = ["wtb_name", "wtb_sku", "demand_count", "my_product_name", "my_product_price", "my_product_url"]
        else:
            fields = ["my_product_name", "my_product_sku", "my_product_price", "my_product_url"]

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(items)

        logger.info(f"Eksporterede {len(items)} elementer til {filepath}")
        return True


def main():
    """Test sammenligningstjenesten."""
    service = ComparisonService()
    results = service.compare()

    logger.info("=== Sammenligningsresultater ===")
    logger.info(f"Total WTB Elementer: {results['summary']['total_wtb_items']}")
    logger.info(f"Dine Produkter: {results['summary']['total_my_products']}")
    logger.info(f"Mangler (muligheder): {results['summary']['missing_count']}")
    logger.info(f"På Lager (matcher efterspørgsel): {results['summary']['in_stock_count']}")
    logger.info(f"Ingen Efterspørgsel: {results['summary']['no_demand_count']}")

    if results["missing"]:
        logger.info("=== Top 5 Manglende Elementer (Muligheder) ===")
        for item in results["missing"][:5]:
            logger.info(f"  - {item['wtb_name']} (Efterspørgsel: {item['demand_count']})")


if __name__ == "__main__":
    main()
