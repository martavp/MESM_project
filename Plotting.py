#!/usr/bin/env python
# coding: utf-8

import pypsa
import cartopy
import cartopy.crs as ccrs
import cartopy.mpl.geoaxes
from matplotlib.patches import Circle, Ellipse
from matplotlib.legend_handler import HandlerPatch
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

def assign_location(n):
    for c in n.iterate_components(n.one_port_components | n.branch_components):

        ifind = pd.Series(c.df.index.str.find(" ", start=3), c.df.index)

        for i in ifind.value_counts().index:
            # these have already been assigned defaults
            if i == -1:
                continue

            names = ifind.index[ifind == i]

            c.df.loc[names, 'location'] = names.str[:i]

def rename_techs(label):

#     prefix_to_remove = ["residential ","services ","urban ","rural ","central ","decentral "]
#     rename_if_contains = ["CHP","gas boiler","biogas"]
#     rename_if_contains_dict = {"battery" : "battery storage"}
    rename = {"solar" : "solar PV",
              "offshorewind" : "offshore wind",
              "offshorewind-ac" : "offshore wind (AC)",
              "offshorewind-dc" : "offshore wind (DC)",
              "onshorewind" : "onshore wind",
              "ror" : "hydroelectricity",
              "hydro" : "hydroelectricity",
              "PHS" : "hydroelectricity",
              "AC": "transmission"}

#     for ptr in prefix_to_remove:
#         if label[:len(ptr)] == ptr:
#             label = label[len(ptr):]

#     for rif in rename_if_contains:
#         if rif in label:
#             label = rif

#     for old,new in rename_if_contains_dict.items():
#         if old in label:
#             label = new

    for old,new in rename.items():
        if old == label:
            label = new
    return label


def rename_techs_tyndp(tech):
    tech = rename_techs(tech)
#     if "heat pump" in tech or "resistive heater" in tech:
#         return "power-to-heat"
#     elif tech in ["methanation", "hydrogen storage", "helmeth"]:
#         return "power-to-gas"
    if tech == 'OCGT':
        return 'gas'
#     elif tech in ["CHP", "gas boiler"]:
#         return "gas-to-power/heat"
    elif "solar" in tech:
        return "solar PV"
#     elif tech == "Fischer-Tropsch":
#         return "power-to-liquid"
#     elif "offshore wind" in tech:
#         return "offshore wind"
    else:
        return tech

def make_legend_circles_for(sizes, scale=1.0, **kw):
    return [Circle((0, 0), radius=(s / scale)**0.5, **kw) for s in sizes]

def make_handler_map_to_scale_circles_as_in(ax, dont_resize_actively=False):
    fig = ax.get_figure()

    def axes2pt():
        return np.diff(ax.transData.transform([(0, 0), (1, 1)]), axis=0)[
            0] * (72. / fig.dpi)

    ellipses = []
    if not dont_resize_actively:
        def update_width_height(event):
            dist = axes2pt()
            for e, radius in ellipses:
                e.width, e.height = 2. * radius * dist
        fig.canvas.mpl_connect('resize_event', update_width_height)
        ax.callbacks.connect('xlim_changed', update_width_height)
        ax.callbacks.connect('ylim_changed', update_width_height)

    def legend_circle_handler(legend, orig_handle, xdescent, ydescent,
                              width, height, fontsize):
        w, h = 2. * orig_handle.get_radius() * axes2pt()
        e = Ellipse(xy=(0.5 * width - 0.5 * xdescent, 0.5 *
                        height - 0.5 * ydescent), width=w, height=w)
        ellipses.append((e, orig_handle.get_radius()))
        return e
    return {Circle: HandlerPatch(patch_func=legend_circle_handler)}

def plot_map(network, tech_colors, threshold=10,components=["links", "stores", "generators"],
             bus_size_factor=1e6, transmission=True):
    
    fig, ax = plt.subplots(subplot_kw={"projection": ccrs.PlateCarree()})
    n = network.copy()
    assign_location(n)

    preferred_order = pd.Index(["transmission","onshore wind","offshore wind",
                                "solar PV","gas","H2"])
    
    # Drop non-electric buses so they don't clutter the plot
    n.buses.drop(n.buses.index[n.buses.carrier != "AC"], inplace=True)
    costs = pd.DataFrame(index=n.buses.index)
    capacity = pd.DataFrame(index=n.buses.index)
    
    if "stores" in components:
        legend_size = n.stores.e_nom_opt.max()
        unit_string = 'GWh'
        plot_item = 'storage'
    else:
        legend_size = n.generators.groupby('bus').sum().p_nom_opt.max()
        unit_string = 'GW'
        plot_item = 'power'
    
    for comp in components:
        df_c = getattr(n, comp)
        if len(df_c) == 0:
            continue # Some countries might not have e.g. storage_units
        df_c["nice_group"] = df_c.carrier.map(rename_techs_tyndp)
        attr = "e_nom_opt" if comp == "stores" else "p_nom_opt"
        capacity_c = ((df_c[attr])
                    .groupby([df_c.location, df_c.nice_group]).sum()
                    .unstack().fillna(0.))
        costs_c = ((df_c.capital_cost * df_c[attr])
                   .groupby([df_c.location, df_c.nice_group]).sum()
                   .unstack().fillna(0.))
        costs = pd.concat([costs, costs_c], axis=1)
        capacity = pd.concat([capacity, capacity_c], axis=1)
    plot = capacity.groupby(capacity.columns, axis=1).sum()

    plot.drop(columns=plot.sum().loc[plot.sum() < threshold].index,inplace=True)
    technologies = plot.columns
    plot.drop(list(plot.columns[(plot == 0.).all()]), axis=1, inplace=True)
    new_columns = preferred_order[preferred_order.isin(plot.columns)]
    plot = plot[new_columns]
    for item in new_columns:
        if item not in tech_colors:
            print("Warning!",item,"not defined in tech_colors")
    plot = plot.stack()  # .sort_index()
    to_drop = plot.index.levels[0].symmetric_difference(n.buses.index)
    if len(to_drop) != 0:
        print("dropping non-buses", to_drop)
        plot.drop(to_drop, level=0, inplace=True, axis=0)
    # make sure they are removed from index
    plot.index = pd.MultiIndex.from_tuples(plot.index.values)
    # PDF has minimum width, so set these to zero
    line_lower_threshold = 100
    line_upper_threshold = 1000
    linewidth_factor = 50
    ac_color = "gray"
    dc_color = "m"
    links = n.links
    lines = n.lines
    line_widths = lines.s_nom_opt - lines.s_nom
    link_widths = links.p_nom_opt - links.p_nom
    if transmission:
        line_widths = lines.s_nom_opt
        link_widths = links.p_nom_opt
        linewidth_factor = 50
        line_lower_threshold = 0.
        
    line_widths[line_widths < line_lower_threshold] = 0.
    link_widths[link_widths < line_lower_threshold] = 0.
    line_widths[line_widths > line_upper_threshold] = line_upper_threshold
    link_widths[link_widths > line_upper_threshold] = line_upper_threshold
    
    fig.set_size_inches(16, 12)
    n.plot(bus_sizes=plot / bus_size_factor,
           bus_colors=tech_colors,
           line_colors=ac_color,
           link_colors=ac_color,
           line_widths=line_widths / linewidth_factor,
           link_widths=link_widths / linewidth_factor,
           ax=ax,
           boundaries=(n.buses.x[n.buses.x>0].min()-5, 
                               n.buses.x[n.buses.x>0].max()+5, 
                               n.buses.y[n.buses.y>0].min()-5, 
                               n.buses.y[n.buses.y>0].max()+5),
           color_geomap={'ocean': 'lightblue', 'land': "palegoldenrod"})

    for i in technologies:
        ax.plot([0,0],[1,1],label=i,color=tech_colors[i],lw=5)
    fig.legend(loc='center right', frameon=False,borderaxespad=1)
    fig.suptitle('Installed ' + plot_item + ' capacities and transmission lines',y=0.92,fontsize=15)
    
    handles = make_legend_circles_for(
        [legend_size/10,legend_size], scale=bus_size_factor, facecolor="white")
    str1 = ["    {:10.0f} ".format(s) for s in (legend_size/10,legend_size)]
    labels = [x + unit_string for x in str1]
    l1 = ax.legend(handles, labels,
                   loc="upper left", bbox_to_anchor=(0.05, 0.96),
                   labelspacing=4,
                   frameon=False,
                   title='',
                   handler_map=make_handler_map_to_scale_circles_as_in(ax))
    ax.add_artist(l1)
    handles = []
    labels = []
    for s in (1000, 100):
        handles.append(plt.Line2D([0], [0], color=ac_color,
                                  linewidth=s / linewidth_factor))
        labels.append("{} MW".format(s))
    l2 = ax.legend(handles, labels,
                    loc="upper left", bbox_to_anchor=(0.3, 0.96),
                    frameon=False,
                    labelspacing=4, handletextpad=1.5,
                    title='')
    ax.add_artist(l2)
    
def line_plot_generation(n,c):
    plt.plot(n.loads_t.p[c][0:96], color='black', label='demand')
    plt.plot(n.generators_t.p[c + ' onshorewind'][0:96], color='blue', label='onshore wind')
    plt.plot(n.generators_t.p[c + ' solar'][0:96], color='orange', label='solar')
    plt.plot(n.generators_t.p[c + ' OCGT'][0:96], color='brown', label='gas (OCGT)')
    plt.legend(fancybox=True, shadow=True, loc='best')

def pie_chart_generation(n,c):
    labels = ['onshore wind', 
          'solar', 
          'gas (OCGT)']
    sizes = [n.generators_t.p[c + ' onshorewind'].sum(),
             n.generators_t.p[c + ' solar'].sum(),
             n.generators_t.p[c + ' OCGT'].sum()]

    colors=['blue', 'orange', 'brown']

    plt.pie(sizes, 
            colors=colors, 
            labels=labels, 
            wedgeprops={'linewidth':0})
    plt.axis('equal')
    plt.title('Electricity mix ' + c, y=1.07)

