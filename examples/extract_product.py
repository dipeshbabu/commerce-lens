from commercelens import extract_product


if __name__ == "__main__":
    result = extract_product(
        "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
    )
    print(result.model_dump_json(indent=2))
