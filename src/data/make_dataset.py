# -*- coding: utf-8 -*-
import logging
import pathlib
import sys

import click
from dotenv import find_dotenv, load_dotenv
import pandas

from src.data import utils

log_fmt = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
logging.basicConfig(level=logging.INFO, format=log_fmt)
LOG = logging.getLogger(__name__)

FILES = [
    "raw/datos_provincias.csv",
    "external/provincias-ine.csv",
    "raw/province_flux_intra.csv",
    "raw/province_flux_inter.csv",
]


def check_data(base_dir):
    LOG.info(f"Checking for needed data in '{base_dir}'")

    error = False
    for f in FILES:
        if not (path := pathlib.Path(base_dir / f)).exists():
            LOG.error(f"Cannot find '{path}'")
            error = True

    if error:
        sys.exit(1)


def prepare_dataset(base_dir):
    df = pandas.read_csv(
        base_dir / "raw" / "datos_provincias.csv",
        keep_default_na=False
    )
    columns = ["province iso", "date",
               "cases new", "cases new (pcr)", "cases new (ac)",
               "cases new (other)", "cases new (unk)"]
    df.columns = columns

    # Only use the colums that we need
    columns = ["province iso", "date", "cases new (pcr)"]
    df = df[columns]
    df["date"] = pandas.to_datetime(df["date"], format="%Y-%m-%d")

    prov = pandas.read_csv(
        base_dir / "external" / "provincias-ine.csv",
        sep=";"
    )

    utils.add_province_info(df, prov)

    # We have new cases only, lets calculate accumulated, and increments

    cols = ["cases new (pcr)"]
    # Calculate cumulative cases
    new_cols = [i.replace("new", "acc") for i in cols]
    df[new_cols] = df.groupby('province id')[cols].cumsum()

    # Calculate cases increment in percentage
    cols = new_cols
    new_cols = [i.replace("acc", "inc") for i in cols]
    df[new_cols] = df.groupby(['province'])[cols].pct_change() * 100
    df[new_cols] = df[new_cols].fillna(value=0)

    f = base_dir / "processed" / "provinces.csv"
    LOG.info(f"Writing province data to '{f}', {df.shape[0]} observations")
    df.to_csv(
        f,
        index=False,
    )

    # Now generate a dataset that contains a column-based matrix of mobility
    # fluxes, with the rows the destination province, columns the origin.
    mob_inter = pandas.read_csv(
        base_dir / "raw" / "province_flux_inter.csv",
        parse_dates=[0],
    )
    mob_intra = pandas.read_csv(
        base_dir / "raw" / "province_flux_intra.csv",
        parse_dates=[0],
    )

    mob_by_columns = base_dir / "interim" / "province_flux_by_destination.csv"
    if not mob_by_columns.exists():
        LOG.info(f"Generating mobility dataset by columns {mob_by_columns}, "
                 "with rows as destination province")

        # Read mobility, change to columns, with rows as destination
        mob_origin = pandas.DataFrame(columns=["date", "province destination"])
        for date in mob_inter["date"].unique():
            for p in df["province"].unique():
                aux = mob_inter.loc[
                    (mob_inter["province destination"] == p) &
                    (mob_inter["date"] == date),
                    ["province origin", "flux"]
                ]
                aux = aux.set_index("province origin").T
                aux.insert(0, "date", date)
                aux.insert(1, "province destination", p)
                aux[p] = mob_intra.loc[
                    (mob_intra["province"] == p) & (mob_intra["date"] == date),
                    "flux"
                ].values[0]

                mob_origin = mob_origin.append(aux)

        mob_origin = mob_origin.reset_index(drop=True).fillna(value=0)
        LOG.info("Writing interim mobility dataset by columns "
                 f"{mob_by_columns}, with rows as destination province, "
                 f"{mob_origin.shape[0]} observations")

        mob_origin.to_csv(
            mob_by_columns,
            index=False,
        )
    else:
        mob_origin = pandas.read_csv(
            mob_by_columns,
            parse_dates=[0],
        )
        LOG.info("Using existing mobility dataset by columns "
                 f"{mob_by_columns}, with rows as destination province, "
                 f"{mob_origin.shape[0]} observations")

    merged = df.merge(
        mob_origin,
        left_on=["date", "province"],
        right_on=["date", "province destination"]
    )

    f = base_dir / "processed" / "provinces-mobility.csv"
    LOG.info(f"Writing province +  mobility data to '{f}', {merged.shape[0]} "
             "observations")
    merged.to_csv(
        f,
        index=False,
    )


@click.command()
@click.argument('base_dir', type=click.Path(exists=True))
def main(base_dir):
    """ Runs data processing scripts to turn raw data from (../raw) into
        cleaned data ready to be analyzed (saved in ../processed).
    """
    LOG.info('making final data set from raw data')

    base_dir = pathlib.Path(base_dir)
    check_data(base_dir)
    prepare_dataset(base_dir)


if __name__ == '__main__':

    # not used in this stub but often useful for finding various files
    project_dir = pathlib.Path(__file__).resolve().parents[2]

    # find .env automagically by walking up directories until it's found, then
    # load up the .env entries as environment variables
    load_dotenv(find_dotenv())

    main()
