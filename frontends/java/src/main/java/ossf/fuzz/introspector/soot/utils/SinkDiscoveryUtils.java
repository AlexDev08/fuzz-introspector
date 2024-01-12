// Copyright 2024 Fuzz Introspector Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
///////////////////////////////////////////////////////////////////////////

package ossf.fuzz.introspector.soot.utils;

import java.util.LinkedList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import soot.SootClass;
import soot.SootMethod;

public class SinkDiscoveryUtils {
  /**
   * The method loop through all methods and classes for the target
   * project and discover all sink methods existed in the project.
   *
   * @param sinkMethodMap the sink methods and classes to look for
   * @param projectClassMethodMap all methods and classes in the project
   * @return a list of sink methods exist in the project
   */
  public static List<SootMethod> discoverAllSinks(Map<String, Set<String>> sinkMethodMap, Map<SootClass, List<SootMethod>> projectClassMethodMap) {
    List<SootMethod> sinkMethods = new LinkedList<SootMethod>();

    // Loop through all classes and methods of the project
    for (SootClass c : projectClassMethodMap.keySet()) {
      // Only process classes with sink methods
      if (sinkMethodMap.containsKey(c.getName())) {
        // Temporary SootMethod list to avoid concurrent modification
        List<SootMethod> mList = new LinkedList<SootMethod>();
        mList.addAll(projectClassMethodMap.get(c));
        for (SootMethod m : mList) {
          if (sinkMethodMap.get(c.getName()).contains(m.getName())) {
            // Add the found sink method to the result list
            sinkMethods.add(m);
          }
        }
      }
    }

    return sinkMethods;
  }
}
