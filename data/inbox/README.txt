Drop plain-text (.txt) legal documents here.

If `scripts/watch.sh` is running, each file is automatically:
  1. chunked + embedded (searchable in the archive)
  2. structure-extracted (parties, representation, events, entities -> a case Entry)
then moved to data/inbox/done/.

Without the watcher, run once:  python -m scripts.add data/inbox --move-to data/inbox/done
