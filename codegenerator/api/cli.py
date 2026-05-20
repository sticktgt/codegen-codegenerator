from __future__ import annotations
import argparse, json
from codegenerator.api.service import generate_from_file, repair_from_file, generate_test_from_file, review_generated_test_failure_from_file

def main() -> None:
    parser = argparse.ArgumentParser(prog='codegenerator')
    sub = parser.add_subparsers(dest='cmd', required=True)
    g = sub.add_parser('generate')
    g.add_argument('--request-file', required=True)
    g.add_argument('--config', default='config.yaml')
    t = sub.add_parser('generate-test')
    t.add_argument('--request-file', required=True)
    t.add_argument('--config', default='config.yaml')
    r = sub.add_parser('repair')
    r.add_argument('--request-file', required=True)
    r.add_argument('--config', default='config.yaml')
    rv = sub.add_parser('review-generated-test-failure')
    rv.add_argument('--request-file', required=True)
    rv.add_argument('--config', default='config.yaml')
    args = parser.parse_args()
    if args.cmd=='generate':
        print(json.dumps(generate_from_file(args.request_file, args.config), ensure_ascii=False, indent=2))
    elif args.cmd=='generate-test':
        print(json.dumps(generate_test_from_file(args.request_file, args.config), ensure_ascii=False, indent=2))
    elif args.cmd=='repair':
        print(json.dumps(repair_from_file(args.request_file, args.config), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(review_generated_test_failure_from_file(args.request_file, args.config), ensure_ascii=False, indent=2))
